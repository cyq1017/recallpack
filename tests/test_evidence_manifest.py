import copy
import hashlib
import importlib
import unittest

from tests.v4_evidence_fixtures import (
    EXECUTION_MANIFEST_SHA256,
    build_aggregate_artifact_hashes,
    build_aggregate_report,
    build_artifact_bytes,
    build_evaluation_run,
    build_floor_execution_manifest,
    build_full_execution_manifest,
    build_image_build_record,
    build_relation_label_ledger,
    build_source_ledger,
    build_simulated_external_holdout_bundle,
    build_test_only_simulated_complete_evidence_packet,
    build_test_only_simulated_valid_manifest_red_packet,
    canonical_json_bytes,
    canonical_sha256,
    definition_validator,
)


def _import_evidence():
    return importlib.import_module("recallpack.evidence")


class EvidenceManifestRedTests(unittest.TestCase):
    def _assert_semantic_reject(self, fn, *args, code: str, **kwargs):
        with self.assertRaisesRegex(ValueError, code):
            fn(*args, **kwargs)

    def _evidence_validate_kwargs(self, packet, predecessor_manifest=None):
        return {
            "retained_attempt_loader": packet["retained_attempt_loader"],
            "artifact_bytes": packet["artifact_bytes"],
            "source_ledgers": packet["all_source_ledgers"],
            "relation_label_ledgers": packet["all_relation_label_ledgers"],
            "predecessor_manifest": predecessor_manifest,
        }

    def test_schema_builders_are_valid_and_closed(self):
        packet = build_test_only_simulated_valid_manifest_red_packet()
        records = {
            "sourceLedger": packet["source_ledgers"]["projectodyssey"],
            "relationLabelLedger": packet["relation_label_ledgers"]["projectodyssey"],
            "imageBuildRecord": build_image_build_record(),
            "legacyManifest40": packet["manifest"],
            "run": packet["run"],
            "aggregate": packet["aggregate"],
            "evidenceManifest": packet["evidence"],
        }
        for name, payload in records.items():
            with self.subTest(name=name):
                self.assertEqual(
                    [], list(definition_validator(name).iter_errors(payload))
                )
                invalid = copy.deepcopy(payload)
                invalid["unexpected"] = True
                self.assertTrue(list(definition_validator(name).iter_errors(invalid)))

    def test_floor_manifest_rejects_noncanonical_structural_claim_at_generic_boundary(
        self,
    ):
        source_ledger = build_source_ledger("diag-project-a")
        relation_ledger = build_relation_label_ledger(
            "diag-project-a", source_ledger, entries=[]
        )
        manifest = build_floor_execution_manifest(
            source_ledgers={"diag-project-a": source_ledger},
            relation_label_ledgers={"diag-project-a": relation_ledger},
        )
        manifest["claim_declarations"][0]["statement"] = (
            "The diagnostic proves RecallPack wins."
        )
        self._assert_semantic_reject(
            _import_evidence().validate_execution_manifest,
            manifest,
            artifact_bytes=build_artifact_bytes(
                manifest,
                source_ledgers={"diag-project-a": source_ledger},
            ),
            source_ledgers={"diag-project-a": source_ledger},
            code="invalid_claim_reference",
        )

    def test_aggregate_schema_rejects_unknown_metric_ids_duplicate_metrics_incompatible_claim_metric_and_invalid_hash_keys(
        self,
    ):
        manifest = build_full_execution_manifest(
            simulated_external_holdout=build_simulated_external_holdout_bundle()
        )
        run = build_evaluation_run(manifest)
        aggregate = build_aggregate_report(manifest, run_records=[run])
        self.assertEqual(
            [], list(definition_validator("aggregate").iter_errors(aggregate))
        )
        self.assertEqual(
            aggregate["artifact_hashes"],
            build_aggregate_artifact_hashes(manifest, [run]),
        )

        unknown_metric = copy.deepcopy(aggregate)
        unknown_metric["metrics"][0]["metric_id"] = "unknown_metric"
        self.assertTrue(
            list(definition_validator("aggregate").iter_errors(unknown_metric))
        )

        duplicate_metrics = copy.deepcopy(aggregate)
        duplicate_metrics["metrics"].append(
            copy.deepcopy(duplicate_metrics["metrics"][0])
        )
        self.assertTrue(
            list(definition_validator("aggregate").iter_errors(duplicate_metrics))
        )

        incompatible_claim_metric = copy.deepcopy(aggregate)
        incompatible_claim_metric["claim_id"] = "claim_false_supersession"
        incompatible_claim_metric["claim_type"] = "false_supersession_rate"
        self.assertTrue(
            list(
                definition_validator("aggregate").iter_errors(incompatible_claim_metric)
            )
        )

        zero_denominator = copy.deepcopy(aggregate)
        zero_denominator["metrics"][0].update(
            {"n": 0, "numerator": 0, "denominator": 0, "rate": 0.0}
        )
        self.assertTrue(
            list(definition_validator("aggregate").iter_errors(zero_denominator))
        )
        zero_denominator["metrics"][0]["rate"] = None
        self.assertEqual(
            [], list(definition_validator("aggregate").iter_errors(zero_denominator))
        )

        bad_hash_keys = copy.deepcopy(aggregate)
        bad_hash_keys["artifact_hashes"] = {"report": "0" * 64}
        self.assertTrue(
            list(definition_validator("aggregate").iter_errors(bad_hash_keys))
        )

    def test_execution_manifest_semantic_rejections_cover_roots_refs_custody_and_claims(
        self,
    ):
        packet = build_test_only_simulated_valid_manifest_red_packet()
        evidence_module = _import_evidence()
        validate = evidence_module.validate_legacy_execution_manifest_diagnostic

        validate(
            packet["manifest"],
            artifact_bytes=packet["artifact_bytes"],
            source_ledgers=packet["source_ledgers"],
        )

        self.assertEqual(
            packet["manifest"]["label_hashes"]["projectodyssey"],
            packet["manifest"]["evidence_scenarios"][0]["relation_label_ledger_sha256"],
        )
        self.assertEqual(
            packet["artifact_bytes"]["label_projectodyssey"].decode("utf-8"),
            packet["manifest"]["evidence_scenarios"][0]["relation_label_ledger_sha256"],
        )

        bad_build_record_schema = dict(packet["artifact_bytes"])
        bad_build_record_schema["image_build_record"] = canonical_json_bytes(
            {"record_type": "image_build_record"}
        )
        with self.assertRaises(ValueError) as excinfo:
            validate(
                packet["manifest"],
                artifact_bytes=bad_build_record_schema,
                source_ledgers=packet["source_ledgers"],
            )
        self.assertIn("invalid_artifact_reference", str(excinfo.exception))
        self.assertNotIn("invalid_execution_manifest", str(excinfo.exception))

        bad_build_root = copy.deepcopy(packet["manifest"])
        bad_build_root["evaluator_contract"]["build_context_root"] = "wrong-root/"
        self._assert_semantic_reject(
            validate,
            bad_build_root,
            artifact_bytes=packet["artifact_bytes"],
            source_ledgers=packet["source_ledgers"],
            code="invalid_artifact_reference",
        )

        forbidden_output_kind = copy.deepcopy(packet["manifest"])
        forbidden_output_kind["input_artifact_catalog"]["run_eval_A1"] = {
            "kind": "evaluation_run",
            "relative_path": "runs/eval_A1.json",
            "sha256": "7" * 64,
            "bytes": 64,
            "sanitized": True,
            "content_policy": "sanitized_bounded",
        }
        self._assert_semantic_reject(
            validate,
            forbidden_output_kind,
            artifact_bytes=packet["artifact_bytes"],
            source_ledgers=packet["source_ledgers"],
            code="invalid_artifact_reference",
        )

        broken_ledger_ref = copy.deepcopy(packet["manifest"])
        broken_ledger_ref["evidence_scenarios"][0]["source_ledger_artifact_id"] = (
            "missing_ledger"
        )
        self._assert_semantic_reject(
            validate,
            broken_ledger_ref,
            artifact_bytes=packet["artifact_bytes"],
            source_ledgers=packet["source_ledgers"],
            code="invalid_artifact_reference",
        )

        duplicate_source_refs = copy.deepcopy(packet["source_ledgers"])
        duplicate_source_refs["projectodyssey"]["entries"][1]["source_ref"] = (
            duplicate_source_refs["projectodyssey"]["entries"][0]["source_ref"]
        )
        self._assert_semantic_reject(
            validate,
            packet["manifest"],
            artifact_bytes=packet["artifact_bytes"],
            source_ledgers=duplicate_source_refs,
            code="invalid_artifact_reference",
        )

        mismatched_label_hash = copy.deepcopy(packet["manifest"])
        mismatched_label_hash["label_hashes"]["projectodyssey"] = "0" * 64
        self._assert_semantic_reject(
            validate,
            mismatched_label_hash,
            artifact_bytes=packet["artifact_bytes"],
            source_ledgers=packet["source_ledgers"],
            code="invalid_artifact_reference",
        )

        mismatched_label_payload = copy.deepcopy(packet["artifact_bytes"])
        mismatched_label_payload["label_projectodyssey"] = ("1" * 64).encode("utf-8")
        self._assert_semantic_reject(
            validate,
            packet["manifest"],
            artifact_bytes=mismatched_label_payload,
            source_ledgers=packet["source_ledgers"],
            code="invalid_artifact_reference",
        )

        revealed_holdout = copy.deepcopy(packet["manifest"])
        revealed_holdout["evidence_scenarios"][3]["source_ledger_artifact_id"] = (
            "ledger_graphiti"
        )
        self._assert_semantic_reject(
            validate,
            revealed_holdout,
            artifact_bytes=packet["artifact_bytes"],
            source_ledgers=packet["source_ledgers"],
            code="invalid_custody_state|invalid_artifact_reference",
        )

        floor_manifest = build_floor_execution_manifest()
        floor_manifest["claim_declarations"].append(
            {
                "claim_id": "claim_invalid_floor",
                "claim_type": "downstream_superiority",
                "activation_rule_id": "sc005_downstream_superiority",
                "eligible_rungs": ["Full"],
                "statement": "Invalid for Floor.",
                "rerunnable_command": "python -m unittest",
                "limitations": ["Floor cannot declare conditional claims."],
            }
        )
        self._assert_semantic_reject(
            evidence_module.validate_execution_manifest,
            floor_manifest,
            artifact_bytes=packet["artifact_bytes"],
            source_ledgers={
                "diag-project-a": packet["source_ledgers"]["projectodyssey"]
            },
            code="invalid_rung_grid|invalid_claim_reference",
        )

    def test_run_semantic_rejections_cover_context_refs_usage_sandbox_and_budget(self):
        packet = build_test_only_simulated_valid_manifest_red_packet()
        evidence_module = _import_evidence()
        validate = evidence_module.validate_legacy_evaluation_run_diagnostic

        validate(
            packet["run"],
            packet["manifest"],
            artifact_bytes=packet["artifact_bytes"],
            source_ledger=packet["source_ledgers"]["projectodyssey"],
        )

        bad_context_hash = copy.deepcopy(packet["run"])
        bad_context_hash["context_evidence"]["sha256"] = "0" * 64
        self._assert_semantic_reject(
            validate,
            bad_context_hash,
            packet["manifest"],
            artifact_bytes=packet["artifact_bytes"],
            source_ledger=packet["source_ledgers"]["projectodyssey"],
            code="invalid_context_evidence",
        )

        unknown_output_ref = copy.deepcopy(packet["run"])
        unknown_output_ref["patch"]["diff_artifact_id"] = "missing_patch"
        self._assert_semantic_reject(
            validate,
            unknown_output_ref,
            packet["manifest"],
            artifact_bytes=packet["artifact_bytes"],
            source_ledger=packet["source_ledgers"]["projectodyssey"],
            code="invalid_artifact_reference",
        )

        orphan_patched_file = copy.deepcopy(packet["run"])
        retained_file = orphan_patched_file["run_output_artifact_catalog"][
            "patched_file_retry"
        ]
        orphan_record = copy.deepcopy(retained_file)
        orphan_record["relative_path"] = (
            "runs/eval_projectodyssey_semantic_rerank_001/"
            "patched-files/src/retry_policy.py"
        )
        orphan_patched_file["run_output_artifact_catalog"][
            "orphan_patched_file"
        ] = orphan_record
        orphan_patched_file["artifact_hashes"]["orphan_patched_file"] = (
            orphan_record["sha256"]
        )
        orphan_artifacts = copy.deepcopy(packet["artifact_bytes"])
        orphan_artifacts["orphan_patched_file"] = orphan_artifacts[
            "patched_file_retry"
        ]
        self._assert_semantic_reject(
            validate,
            orphan_patched_file,
            packet["manifest"],
            artifact_bytes=orphan_artifacts,
            source_ledger=packet["source_ledgers"]["projectodyssey"],
            code="invalid_artifact_reference",
        )

        unbacked_patch_file = copy.deepcopy(packet["run"])
        unbacked_patch_file["patch"]["files"][0]["sha256"] = "0" * 64
        self._assert_semantic_reject(
            validate,
            unbacked_patch_file,
            packet["manifest"],
            artifact_bytes=packet["artifact_bytes"],
            source_ledger=packet["source_ledgers"]["projectodyssey"],
            code="invalid_artifact_reference",
        )

        duplicate_path = copy.deepcopy(packet["run"])
        duplicate_path["patch"]["files"].append(
            copy.deepcopy(duplicate_path["patch"]["files"][0])
        )
        self._assert_semantic_reject(
            validate,
            duplicate_path,
            packet["manifest"],
            artifact_bytes=packet["artifact_bytes"],
            source_ledger=packet["source_ledgers"]["projectodyssey"],
            code="invalid_artifact_reference",
        )

        divergent_diff = copy.deepcopy(packet["run"])
        divergent_artifacts = copy.deepcopy(packet["artifact_bytes"])
        divergent_artifacts["patch_diff"] = (
            b"--- a/src/retry.py\n+++ b/src/retry.py\n@@ -1 +1 @@\n-old\n+unrelated\n"
        )
        divergent_diff["run_output_artifact_catalog"]["patch_diff"]["sha256"] = (
            hashlib.sha256(divergent_artifacts["patch_diff"]).hexdigest()
        )
        divergent_diff["run_output_artifact_catalog"]["patch_diff"]["bytes"] = len(
            divergent_artifacts["patch_diff"]
        )
        divergent_diff["artifact_hashes"]["patch_diff"] = divergent_diff[
            "run_output_artifact_catalog"
        ]["patch_diff"]["sha256"]
        divergent_diff["patch"]["diff_sha256"] = divergent_diff[
            "run_output_artifact_catalog"
        ]["patch_diff"]["sha256"]
        self._assert_semantic_reject(
            validate,
            divergent_diff,
            packet["manifest"],
            artifact_bytes=divergent_artifacts,
            source_ledger=packet["source_ledgers"]["projectodyssey"],
            code="invalid_artifact_reference",
        )

        out_of_allowlist_patch_file = copy.deepcopy(packet["run"])
        out_of_allowlist_patch_file["patch"]["files"][0]["path"] = "README.md"
        self._assert_semantic_reject(
            validate,
            out_of_allowlist_patch_file,
            packet["manifest"],
            artifact_bytes=packet["artifact_bytes"],
            source_ledger=packet["source_ledgers"]["projectodyssey"],
            code="invalid_artifact_reference",
        )

        bad_usage = copy.deepcopy(packet["run"])
        bad_usage["usage"]["provider_calls"] = 99
        self._assert_semantic_reject(
            validate,
            bad_usage,
            packet["manifest"],
            artifact_bytes=packet["artifact_bytes"],
            source_ledger=packet["source_ledgers"]["projectodyssey"],
            code="invalid_provider_trace|invalid_run_arithmetic",
        )

        bad_sandbox = copy.deepcopy(packet["run"])
        bad_sandbox["test_result"]["sandbox"]["network_none"] = False
        self._assert_semantic_reject(
            validate,
            bad_sandbox,
            packet["manifest"],
            artifact_bytes=packet["artifact_bytes"],
            source_ledger=packet["source_ledgers"]["projectodyssey"],
            code="invalid_sandbox_evidence",
        )

        over_budget = copy.deepcopy(packet["run"])
        over_budget["context_evidence"]["exact_token_count"] = 513
        self._assert_semantic_reject(
            validate,
            over_budget,
            packet["manifest"],
            artifact_bytes=packet["artifact_bytes"],
            source_ledger=packet["source_ledgers"]["projectodyssey"],
            code="invalid_context_evidence",
        )

    def test_run_semantic_rejections_cover_manifest_binding_designation_sources_and_hashes(
        self,
    ):
        packet = build_test_only_simulated_valid_manifest_red_packet()
        evidence_module = _import_evidence()
        validate = evidence_module.validate_legacy_evaluation_run_diagnostic

        bad_run_schema = copy.deepcopy(packet["run"])
        bad_run_schema["context_evidence"]["tokenizer"]["encoding"] = "cl100k_base"
        with self.assertRaises(ValueError) as excinfo:
            validate(
                bad_run_schema,
                packet["manifest"],
                artifact_bytes=packet["artifact_bytes"],
                source_ledger=packet["source_ledgers"]["projectodyssey"],
            )
        self.assertIn("invalid_context_evidence", str(excinfo.exception))
        self.assertNotIn("invalid_execution_manifest", str(excinfo.exception))

        bad_source_ledger_schema = copy.deepcopy(
            packet["source_ledgers"]["projectodyssey"]
        )
        bad_source_ledger_schema["entries"][0]["unexpected"] = True
        with self.assertRaises(ValueError) as excinfo:
            validate(
                packet["run"],
                packet["manifest"],
                artifact_bytes=packet["artifact_bytes"],
                source_ledger=bad_source_ledger_schema,
            )
        self.assertIn("invalid_run_reference", str(excinfo.exception))
        self.assertNotIn("invalid_execution_manifest", str(excinfo.exception))

        bad_manifest_hash = copy.deepcopy(packet["run"])
        bad_manifest_hash["execution_manifest_sha256"] = "0" * 64
        self._assert_semantic_reject(
            validate,
            bad_manifest_hash,
            packet["manifest"],
            artifact_bytes=packet["artifact_bytes"],
            source_ledger=packet["source_ledgers"]["projectodyssey"],
            code="invalid_run_reference",
        )

        bad_designation = copy.deepcopy(packet["run"])
        bad_designation["designation"] = "diagnostic"
        self._assert_semantic_reject(
            validate,
            bad_designation,
            packet["manifest"],
            artifact_bytes=packet["artifact_bytes"],
            source_ledger=packet["source_ledgers"]["projectodyssey"],
            code="invalid_designation",
        )

        bad_selected_source = copy.deepcopy(packet["run"])
        bad_selected_source["selected_sources"] = ["projectodyssey:missing"]
        self._assert_semantic_reject(
            validate,
            bad_selected_source,
            packet["manifest"],
            artifact_bytes=packet["artifact_bytes"],
            source_ledger=packet["source_ledgers"]["projectodyssey"],
            code="invalid_run_reference",
        )

        bad_provider_identity = copy.deepcopy(packet["run"])
        bad_provider_identity["provider_traces"][0]["model_name"] = "wrong-model"
        self._assert_semantic_reject(
            validate,
            bad_provider_identity,
            packet["manifest"],
            artifact_bytes=packet["artifact_bytes"],
            source_ledger=packet["source_ledgers"]["projectodyssey"],
            code="invalid_provider_trace",
        )

        bad_test_counts = copy.deepcopy(packet["run"])
        bad_test_counts["test_result"]["passed"] = 99
        self._assert_semantic_reject(
            validate,
            bad_test_counts,
            packet["manifest"],
            artifact_bytes=packet["artifact_bytes"],
            source_ledger=packet["source_ledgers"]["projectodyssey"],
            code="invalid_test_result",
        )

        bad_artifact_hashes = copy.deepcopy(packet["run"])
        bad_artifact_hashes["artifact_hashes"]["context_visible"] = "0" * 64
        self._assert_semantic_reject(
            validate,
            bad_artifact_hashes,
            packet["manifest"],
            artifact_bytes=packet["artifact_bytes"],
            source_ledger=packet["source_ledgers"]["projectodyssey"],
            code="invalid_artifact_reference",
        )

        bad_failure_code = build_evaluation_run(
            packet["manifest"],
            designation="invalidated_technical",
        )
        bad_failure_code["failure"]["code"] = "manual_abort"
        self._assert_semantic_reject(
            validate,
            bad_failure_code,
            packet["manifest"],
            artifact_bytes=packet["artifact_bytes"],
            source_ledger=packet["source_ledgers"]["projectodyssey"],
            code="invalid_failure_code",
        )

        repetition_two_slot = next(
            slot["slot_index"]
            for slot in packet["manifest"]["execution_order"]
            if slot["scenario_slot"] == "projectodyssey"
            and slot["variant_id"] == "semantic_rerank"
            and slot["repetition"] == 2
        )
        bad_attempt = build_evaluation_run(
            packet["manifest"],
            slot_index=repetition_two_slot,
            attempt_no=1,
        )
        self._assert_semantic_reject(
            validate,
            bad_attempt,
            packet["manifest"],
            artifact_bytes=packet["artifact_bytes"],
            source_ledger=packet["source_ledgers"]["projectodyssey"],
            code="invalid_replacement",
        )

        bad_test_evidence_kind = copy.deepcopy(packet["run"])
        bad_test_evidence_kind["test_result"]["tests"][0]["evidence_artifact_id"] = (
            "patch_diff"
        )
        self._assert_semantic_reject(
            validate,
            bad_test_evidence_kind,
            packet["manifest"],
            artifact_bytes=packet["artifact_bytes"],
            source_ledger=packet["source_ledgers"]["projectodyssey"],
            code="invalid_artifact_reference",
        )

        bad_provider_token_provenance = copy.deepcopy(packet["run"])
        bad_provider_token_provenance["provider_traces"][0]["token_usage"][
            "reported_by_provider"
        ] = False
        self._assert_semantic_reject(
            validate,
            bad_provider_token_provenance,
            packet["manifest"],
            artifact_bytes=packet["artifact_bytes"],
            source_ledger=packet["source_ledgers"]["projectodyssey"],
            code="invalid_provider_trace",
        )

    def test_evidence_manifest_semantic_rejections_cover_claim_coverage_chain_and_catalogs(
        self,
    ):
        packet = build_test_only_simulated_complete_evidence_packet()
        evidence_module = _import_evidence()
        validate = evidence_module.validate_legacy_evidence_manifest_diagnostic

        self._assert_semantic_reject(
            validate,
            packet["evidence"],
            packet["manifest"],
            code="incomplete_final_evidence",
            **self._evidence_validate_kwargs(
                packet,
                predecessor_manifest=packet["partial_evidence"],
            ),
        )
        validate(
            packet["partial_evidence"],
            packet["manifest"],
            **self._evidence_validate_kwargs(packet),
        )

        omitted_claim = copy.deepcopy(packet["evidence"])
        omitted_claim["claims"] = omitted_claim["claims"][:-1]
        self._assert_semantic_reject(
            validate,
            omitted_claim,
            packet["manifest"],
            code="invalid_claim_reference|incomplete_final_evidence",
            **self._evidence_validate_kwargs(
                packet,
                predecessor_manifest=packet["partial_evidence"],
            ),
        )

        extra_claim = copy.deepcopy(packet["evidence"])
        extra_claim["claims"].append(copy.deepcopy(extra_claim["claims"][0]))
        extra_claim["claims"][-1]["claim_id"] = "claim_extra"
        self._assert_semantic_reject(
            validate,
            extra_claim,
            packet["manifest"],
            code="invalid_claim_reference",
            **self._evidence_validate_kwargs(
                packet,
                predecessor_manifest=packet["partial_evidence"],
            ),
        )

        duplicate_claim = copy.deepcopy(packet["evidence"])
        duplicate_claim["claims"].append(copy.deepcopy(duplicate_claim["claims"][0]))
        self._assert_semantic_reject(
            validate,
            duplicate_claim,
            packet["manifest"],
            code="invalid_claim_reference",
            **self._evidence_validate_kwargs(
                packet,
                predecessor_manifest=packet["partial_evidence"],
            ),
        )

        broken_catalog = copy.deepcopy(packet["evidence"])
        first_run_id = packet["all_runs"][0]["run_id"]
        broken_catalog["output_artifact_catalog"].pop(f"run_{first_run_id}")
        self._assert_semantic_reject(
            validate,
            broken_catalog,
            packet["manifest"],
            code="invalid_output_catalog|invalid_run_reference",
            **self._evidence_validate_kwargs(
                packet,
                predecessor_manifest=packet["partial_evidence"],
            ),
        )

        schema_invalid_self_hash = copy.deepcopy(packet["evidence"])
        schema_invalid_self_hash["self_sha256"] = EXECUTION_MANIFEST_SHA256
        self.assertTrue(
            list(
                definition_validator("evidenceManifest").iter_errors(
                    schema_invalid_self_hash
                )
            )
        )

        wrong_predecessor_hash = copy.deepcopy(packet["evidence"])
        wrong_predecessor_hash["previous_evidence_manifest_sha256"] = "8" * 64
        self._assert_semantic_reject(
            validate,
            wrong_predecessor_hash,
            packet["manifest"],
            code="invalid_manifest_chain",
            **self._evidence_validate_kwargs(
                packet,
                predecessor_manifest=packet["partial_evidence"],
            ),
        )

        final_predecessor = copy.deepcopy(packet["evidence"])
        final_predecessor["evidence_manifest_id"] = "evidence_FinalPredecessor"
        chained_to_final = copy.deepcopy(packet["evidence"])
        chained_to_final["previous_evidence_manifest_sha256"] = canonical_sha256(
            final_predecessor
        )
        self.assertEqual(
            [],
            list(
                definition_validator("evidenceManifest").iter_errors(
                    final_predecessor
                )
            ),
        )
        self._assert_semantic_reject(
            validate,
            chained_to_final,
            packet["manifest"],
            code="invalid_manifest_chain",
            **self._evidence_validate_kwargs(
                packet,
                predecessor_manifest=final_predecessor,
            ),
        )

        mismatched_output_catalog = copy.deepcopy(packet["artifact_bytes"])
        mismatched_output_catalog[f"run_{first_run_id}"] = b'{"unexpected":"content"}'
        mismatched_kwargs = self._evidence_validate_kwargs(
            packet,
            predecessor_manifest=packet["partial_evidence"],
        )
        mismatched_kwargs["artifact_bytes"] = mismatched_output_catalog
        self._assert_semantic_reject(
            validate,
            packet["evidence"],
            packet["manifest"],
            code="invalid_output_catalog",
            **mismatched_kwargs,
        )

        omitted_run = copy.deepcopy(packet["evidence"])
        omitted_run["run_ids"] = omitted_run["run_ids"][:-1]
        omitted_run["output_artifact_catalog"].pop(
            f"run_{packet['all_runs'][-1]['run_id']}"
        )
        self._assert_semantic_reject(
            validate,
            omitted_run,
            packet["manifest"],
            code="incomplete_final_evidence",
            **self._evidence_validate_kwargs(
                packet,
                predecessor_manifest=packet["partial_evidence"],
            ),
        )

        omitted_aggregate = copy.deepcopy(packet["evidence"])
        omitted_aggregate["aggregate_ids"] = omitted_aggregate["aggregate_ids"][:-1]
        omitted_aggregate["output_artifact_catalog"].pop(
            packet["aggregates"][-1]["aggregate_id"]
        )
        self._assert_semantic_reject(
            validate,
            omitted_aggregate,
            packet["manifest"],
            code="incomplete_final_evidence|invalid_claim_reference",
            **self._evidence_validate_kwargs(
                packet,
                predecessor_manifest=packet["partial_evidence"],
            ),
        )

        wrong_claim_status = copy.deepcopy(packet["evidence"])
        structural_claim = next(
            claim
            for claim in wrong_claim_status["claims"]
            if claim["claim_id"] == "claim_structural_runtime"
        )
        structural_claim["status"] = "disabled"
        structural_claim["decision_reason"] = "threshold_failed"
        self._assert_semantic_reject(
            validate,
            wrong_claim_status,
            packet["manifest"],
            code="invalid_claim_reference|incomplete_final_evidence",
            **self._evidence_validate_kwargs(
                packet,
                predecessor_manifest=packet["partial_evidence"],
            ),
        )

        overstated_downstream = copy.deepcopy(packet["evidence"])
        downstream_claim = next(
            claim
            for claim in overstated_downstream["claims"]
            if claim["claim_id"] == "claim_downstream_superiority"
        )
        downstream_claim["status"] = "enabled"
        downstream_claim["decision_reason"] = "threshold_passed"
        self._assert_semantic_reject(
            validate,
            overstated_downstream,
            packet["manifest"],
            code="invalid_claim_reference|incomplete_final_evidence",
            **self._evidence_validate_kwargs(
                packet,
                predecessor_manifest=packet["partial_evidence"],
            ),
        )

        wrong_claim_evidence = copy.deepcopy(packet["evidence"])
        downstream_claim = next(
            claim
            for claim in wrong_claim_evidence["claims"]
            if claim["claim_id"] == "claim_downstream_superiority"
        )
        downstream_claim["evidence_artifact_ids"] = [
            packet["structural_aggregate"]["aggregate_id"]
        ]
        self._assert_semantic_reject(
            validate,
            wrong_claim_evidence,
            packet["manifest"],
            code="invalid_claim_reference",
            **self._evidence_validate_kwargs(
                packet,
                predecessor_manifest=packet["partial_evidence"],
            ),
        )

        raw_mapping_kwargs = self._evidence_validate_kwargs(
            packet,
            predecessor_manifest=packet["partial_evidence"],
        )
        raw_mapping_kwargs["retained_attempt_loader"] = packet[
            "retained_attempt_authority"
        ]
        self._assert_semantic_reject(
            validate,
            packet["evidence"],
            packet["manifest"],
            code="invalid_output_catalog|incomplete_final_evidence",
            **raw_mapping_kwargs,
        )

    def test_source_and_model_visible_semantics_reject_holdout_reveal_hidden_leaks_and_copied_text(
        self,
    ):
        packet = build_test_only_simulated_valid_manifest_red_packet()
        evidence_module = _import_evidence()
        validate_manifest = evidence_module.validate_legacy_execution_manifest_diagnostic
        validate_run = evidence_module.validate_legacy_evaluation_run_diagnostic

        public_scenarios = packet["manifest"]["evidence_scenarios"][:3]
        holdout_scenario = packet["manifest"]["evidence_scenarios"][3]
        for scenario in public_scenarios:
            with self.subTest(slot=scenario["scenario_slot"]):
                self.assertEqual(
                    sorted(scenario["provenance"]),
                    [
                        "authored_summary_sha256",
                        "commit_refs",
                        "license_id",
                        "source_urls",
                    ],
                )
        self.assertEqual(
            holdout_scenario["source_ledger_artifact_id"], "ledger_holdout_hash"
        )
        self.assertIsNone(holdout_scenario["provenance"])

        leaking_snapshot_bytes = copy.deepcopy(packet["artifact_bytes"])
        leaking_snapshot_bytes["model_visible_snapshot"] = (
            b"hidden_test_name=private_case predicate=fail_if_missing gold_label=id_01"
        )
        self._assert_semantic_reject(
            validate_manifest,
            packet["manifest"],
            artifact_bytes=leaking_snapshot_bytes,
            source_ledgers=packet["source_ledgers"],
            code="invalid_artifact_reference",
        )

        copied_text_bytes = copy.deepcopy(packet["artifact_bytes"])
        copied_text_bytes["prompt_template"] = b"copied source text from upstream file"
        self._assert_semantic_reject(
            validate_manifest,
            packet["manifest"],
            artifact_bytes=copied_text_bytes,
            source_ledgers=packet["source_ledgers"],
            code="invalid_artifact_reference",
        )

        leaking_context_bytes = copy.deepcopy(packet["artifact_bytes"])
        leaking_context_bytes["context_visible"] = (
            b"hidden test content should remain secret; gold_selected=id_09"
        )
        self._assert_semantic_reject(
            validate_run,
            packet["run"],
            packet["manifest"],
            artifact_bytes=leaking_context_bytes,
            source_ledger=packet["source_ledgers"]["projectodyssey"],
            code="invalid_context_evidence|invalid_artifact_reference",
        )


if __name__ == "__main__":
    unittest.main()
