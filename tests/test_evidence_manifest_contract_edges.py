import copy
import importlib
import unittest

from tests.v4_evidence_fixtures import (
    artifact,
    build_test_only_simulated_complete_evidence_packet,
    canonical_json_bytes,
    canonical_sha256,
    definition_validator,
)


def _validate_kwargs(packet):
    return {
        "retained_attempt_loader": packet["retained_attempt_loader"],
        "artifact_bytes": packet["artifact_bytes"],
        "source_ledgers": packet["all_source_ledgers"],
        "relation_label_ledgers": packet["all_relation_label_ledgers"],
        "predecessor_manifest": packet["partial_evidence"],
    }


class EvidenceManifestContractEdgeTests(unittest.TestCase):
    def setUp(self):
        self.packet = build_test_only_simulated_complete_evidence_packet()

    @property
    def validate(self):
        return importlib.import_module(
            "recallpack.evidence"
        ).validate_legacy_evidence_manifest_diagnostic

    def assert_rejected(self, record, *, code, artifact_bytes=None):
        kwargs = _validate_kwargs(self.packet)
        if artifact_bytes is not None:
            kwargs["artifact_bytes"] = artifact_bytes
        with self.assertRaisesRegex(ValueError, code):
            self.validate(record, self.packet["manifest"], **kwargs)

    def test_partial_may_have_no_aggregate_but_final_may_not(self):
        self.assertEqual([], self.packet["partial_evidence"]["aggregate_ids"])
        self.assertEqual(
            [],
            list(
                definition_validator("evidenceManifest").iter_errors(
                    self.packet["partial_evidence"]
                )
            ),
        )
        final_without_aggregates = copy.deepcopy(self.packet["evidence"])
        final_without_aggregates["aggregate_ids"] = []
        self.assertTrue(
            list(
                definition_validator("evidenceManifest").iter_errors(
                    final_without_aggregates
                )
            )
        )

    def test_final_run_set_rejects_schema_valid_unretained_superset(self):
        record = copy.deepcopy(self.packet["evidence"])
        run = copy.deepcopy(self.packet["all_runs"][0])
        run["run_id"] = "eval_ExtraUnretained"
        run_artifact_id = f"run_{run['run_id']}"
        payload = canonical_json_bytes(run)
        record["run_ids"].append(run["run_id"])
        record["output_artifact_catalog"][run_artifact_id] = artifact(
            "evaluation_run",
            f"runs/{run['run_id']}.json",
            payload,
        )
        artifact_bytes = dict(self.packet["artifact_bytes"])
        artifact_bytes[run_artifact_id] = payload

        self.assertEqual(
            [], list(definition_validator("evidenceManifest").iter_errors(record))
        )
        self.assert_rejected(
            record,
            code="incomplete_final_evidence",
            artifact_bytes=artifact_bytes,
        )

    def test_final_aggregate_set_rejects_second_valid_same_claim_aggregate(self):
        record = copy.deepcopy(self.packet["evidence"])
        aggregate = self.packet["subset_structural_aggregate"]
        record["aggregate_ids"].append(aggregate["aggregate_id"])
        record["output_artifact_catalog"][aggregate["aggregate_id"]] = artifact(
            "aggregate_report",
            f"aggregates/{aggregate['aggregate_id']}.json",
            canonical_json_bytes(aggregate),
        )

        self.assertEqual(
            [], list(definition_validator("evidenceManifest").iter_errors(record))
        )
        self.assert_rejected(record, code="incomplete_final_evidence")

    def test_structural_claim_requires_all_retained_run_scope(self):
        record = copy.deepcopy(self.packet["evidence"])
        aggregate = self.packet["subset_structural_aggregate"]
        full_id = self.packet["structural_aggregate"]["aggregate_id"]
        record["aggregate_ids"].remove(full_id)
        record["aggregate_ids"].append(aggregate["aggregate_id"])
        record["output_artifact_catalog"].pop(full_id)
        record["output_artifact_catalog"][aggregate["aggregate_id"]] = artifact(
            "aggregate_report",
            f"aggregates/{aggregate['aggregate_id']}.json",
            canonical_json_bytes(aggregate),
        )
        claim = next(
            item
            for item in record["claims"]
            if item["claim_id"] == "claim_structural_runtime"
        )
        claim["evidence_artifact_ids"] = [aggregate["aggregate_id"]]

        self.assert_rejected(
            record,
            code="invalid_claim_reference|incomplete_final_evidence",
        )

    def test_false_supersession_claim_cannot_ignore_minimum_population(self):
        record = copy.deepcopy(self.packet["evidence"])
        claim = next(
            item
            for item in record["claims"]
            if item["claim_id"] == "claim_false_supersession"
        )
        claim["status"] = "enabled"
        claim["decision_reason"] = "threshold_passed"
        self.assert_rejected(
            record,
            code="invalid_claim_reference|incomplete_final_evidence",
        )

    def test_claim_fields_must_equal_frozen_declaration(self):
        mutations = {
            "statement": "A different public claim.",
            "rerunnable_command": "python3 unexpected.py",
            "limitations": ["A different limitation."],
        }
        for field, value in mutations.items():
            with self.subTest(field=field):
                record = copy.deepcopy(self.packet["evidence"])
                record["claims"][0][field] = value
                self.assert_rejected(record, code="invalid_claim_reference")

    def test_predecessor_must_be_a_semantically_valid_partial_record(self):
        mutations = []
        bad_claim = copy.deepcopy(self.packet["partial_evidence"])
        bad_claim["claims"][0]["statement"] = "A forged predecessor claim."
        mutations.append(bad_claim)

        bad_catalog = copy.deepcopy(self.packet["partial_evidence"])
        run_id = bad_catalog["run_ids"][0]
        bad_catalog["output_artifact_catalog"].pop(f"run_{run_id}")
        mutations.append(bad_catalog)

        bad_version = copy.deepcopy(self.packet["partial_evidence"])
        bad_version["execution_manifest_version"] = "v4-forged"
        mutations.append(bad_version)

        for predecessor in mutations:
            with self.subTest(predecessor=predecessor["evidence_manifest_id"]):
                record = copy.deepcopy(self.packet["evidence"])
                record["previous_evidence_manifest_sha256"] = canonical_sha256(
                    predecessor
                )
                kwargs = _validate_kwargs(self.packet)
                kwargs["predecessor_manifest"] = predecessor
                with self.assertRaisesRegex(ValueError, "invalid_manifest_chain"):
                    self.validate(record, self.packet["manifest"], **kwargs)

    def test_downstream_claim_requires_aggregate_coverage_for_all_sc005_runs(self):
        record = copy.deepcopy(self.packet["evidence"])
        aggregate = self.packet["subset_downstream_aggregate"]
        full_id = self.packet["downstream_aggregate"]["aggregate_id"]
        record["aggregate_ids"].remove(full_id)
        record["aggregate_ids"].append(aggregate["aggregate_id"])
        record["output_artifact_catalog"].pop(full_id)
        record["output_artifact_catalog"][aggregate["aggregate_id"]] = artifact(
            "aggregate_report",
            f"aggregates/{aggregate['aggregate_id']}.json",
            canonical_json_bytes(aggregate),
        )
        claim = next(
            item
            for item in record["claims"]
            if item["claim_id"] == "claim_downstream_superiority"
        )
        claim["evidence_artifact_ids"] = [aggregate["aggregate_id"]]

        self.assert_rejected(
            record,
            code="invalid_claim_reference|incomplete_final_evidence",
        )

    def test_test_only_authority_cannot_validate_final_enabled_full_claim(self):
        packet = build_test_only_simulated_complete_evidence_packet(
            downstream_wins=True
        )
        claim = next(
            item
            for item in packet["evidence"]["claims"]
            if item["claim_id"] == "claim_downstream_superiority"
        )
        self.assertEqual(("enabled", "threshold_passed"), (
            claim["status"],
            claim["decision_reason"],
        ))
        with self.assertRaisesRegex(ValueError, "incomplete_final_evidence"):
            self.validate(
                packet["evidence"],
                packet["manifest"],
                **{
                    **_validate_kwargs(packet),
                    "predecessor_manifest": packet["partial_evidence"],
                },
            )

    def test_output_catalog_paths_must_be_normalized_unique_and_sanitized(self):
        aggregate_id = self.packet["evidence"]["aggregate_ids"][0]
        mutations = []

        noncanonical = copy.deepcopy(self.packet["evidence"])
        noncanonical["output_artifact_catalog"][aggregate_id]["relative_path"] = (
            "aggregates//structural.json"
        )
        mutations.append(noncanonical)

        duplicate = copy.deepcopy(self.packet["evidence"])
        duplicate["output_artifact_catalog"][aggregate_id]["relative_path"] = (
            duplicate["output_artifact_catalog"]["trace_runtime"]["relative_path"]
        )
        mutations.append(duplicate)

        secret_path = copy.deepcopy(self.packet["evidence"])
        secret_path["output_artifact_catalog"][aggregate_id]["relative_path"] = (
            "aggregates/"
            + "api_"
            + "key="
            + "sk-"
            + "123456789012345678901234.json"
        )
        mutations.append(secret_path)

        for record in mutations:
            with self.subTest(
                path=record["output_artifact_catalog"][aggregate_id]["relative_path"]
            ):
                self.assert_rejected(record, code="invalid_output_catalog")

        partial = copy.deepcopy(self.packet["partial_evidence"])
        run_artifact_id = f"run_{partial['run_ids'][0]}"
        partial["output_artifact_catalog"][run_artifact_id]["relative_path"] = (
            "runs//partial.json"
        )
        kwargs = _validate_kwargs(self.packet)
        kwargs["predecessor_manifest"] = None
        with self.assertRaisesRegex(ValueError, "invalid_output_catalog"):
            self.validate(partial, self.packet["manifest"], **kwargs)

    def test_schema_errors_redact_private_paths_and_hosts(self):
        aggregate_id = self.packet["evidence"]["aggregate_ids"][0]
        private_values = [
            "/" + "Users" + "/alice/private-client/result.json",
            "http://" + "127.0.0.1" + "/private-result.json",
        ]
        for private_value in private_values:
            with self.subTest(private_value=private_value):
                record = copy.deepcopy(self.packet["evidence"])
                record["output_artifact_catalog"][aggregate_id]["relative_path"] = (
                    private_value
                )
                with self.assertRaises(ValueError) as raised:
                    self.validate(
                        record,
                        self.packet["manifest"],
                        **_validate_kwargs(self.packet),
                    )
                message = str(raised.exception)
                self.assertIn("invalid_output_catalog", message)
                self.assertNotIn(private_value, message)
                self.assertRegex(message, "private-(?:path|host)-redacted")


if __name__ == "__main__":
    unittest.main()
