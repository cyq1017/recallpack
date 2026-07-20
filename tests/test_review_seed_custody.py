from __future__ import annotations

import copy
import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker

from recallpack.evidence import (
    InMemoryManifestRegistry,
    RevealAuthority,
    assemble_execution_manifest_41,
    canonicalize_review_json,
    compute_frozen_code_hashes,
    materialize_deterministic_bundle,
    resolve_execution_cell_inputs,
    review_json_sha256,
    validate_execution_manifest,
    validate_evaluation_run,
    validate_aggregate_report,
    validate_evidence_manifest,
    validate_legacy_execution_manifest_diagnostic,
    validate_descendant_binding,
    validate_manifest_registration_receipt,
    validate_revealed_external_artifact,
)
from tests._v41_review_seed_fixtures import (
    build_attestation,
    build_external_contents,
    build_full_seed,
    deterministic_bundle,
    materialize_frozen_code_repository,
)
from tests._v41_eligible_registry import seed_test_only_eligible_registration
from tests._v4_evidence_manifest_fixtures import (
    build_execution_input_artifact_bytes,
    build_floor_execution_manifest,
    build_full_execution_manifest,
    build_relation_label_ledgers,
    build_simulated_external_holdout_bundle,
    build_source_ledgers,
)
from recallpack.evidence_custody import (
    _materialize_validated_bundle as materialize_validated_bundle,
)
from tests._v4_evidence_run_fixtures import (
    build_aggregate_report,
    build_evaluation_run,
    build_evidence_manifest,
    build_run_output_artifact_bytes,
)
from tests._v4_evidence_aggregate_fixtures import (
    _relation_opportunities_for_ledger,
    build_test_only_retained_attempt_loader,
)


ROOT = Path(__file__).resolve().parents[1]
SCHEMA = json.loads(
    (ROOT / "specs/001-recallpack-v4/contracts/evaluation.schema.json").read_text()
)


def manifest_validator() -> Draft202012Validator:
    return Draft202012Validator(
        {"$schema": SCHEMA["$schema"], "$defs": SCHEMA["$defs"], "$ref": "#/$defs/manifest"},
        format_checker=FormatChecker(),
    )


class ReviewSeedCustodyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.seed, self.seed_artifacts = build_full_seed()
        self._repository = tempfile.TemporaryDirectory()
        self.addCleanup(self._repository.cleanup)
        self.repository_root = Path(self._repository.name)
        materialize_frozen_code_repository(
            self.repository_root,
            (ROOT / "specs/001-recallpack-v4/contracts/evaluation.schema.json").read_bytes(),
        )
        self.seed["code_hashes"] = compute_frozen_code_hashes(self.repository_root)
        self.external_contents = build_external_contents(self.seed, self.seed_artifacts)
        self.seed_hash = review_json_sha256(self.seed)
        self.attestation, self.receipt = build_attestation(
            self.seed,
            self.seed_hash,
            self.external_contents,
        )
        self.assembled = assemble_execution_manifest_41(
            self.seed,
            self.attestation,
            seed_receipt=self.receipt,
            artifact_bytes=self.seed_artifacts,
            repository_root=self.repository_root,
        )
        self.manifest_hash = review_json_sha256(self.assembled.manifest)

    def registration_receipt(self) -> dict[str, object]:
        return {
            "record_type": "manifest_registration_receipt",
            "receipt_version": "review-receipt/4.1",
            "sequence": 2,
            "receipt_id": "manifest_receipt_test",
            "review_seed_sha256": self.seed_hash,
            "review_attestation_sha256": review_json_sha256(self.attestation),
            "execution_manifest_sha256": self.manifest_hash,
            "registered_at": "2026-07-15T00:03:00Z",
            "registrar_role": "user-custodian",
            "assurance": "procedural",
        }

    def registered_registry(self) -> InMemoryManifestRegistry:
        registry = InMemoryManifestRegistry()
        seed_test_only_eligible_registration(registry, self.assembled.manifest)
        return registry

    def reveal_kind(
        self,
        authority: RevealAuthority,
        slot_id: str,
        attempt_no: int,
        kind: str,
    ) -> None:
        scenario_slot = next(
            item["scenario_slot"]
            for item in self.assembled.manifest["execution_order"]
            if item["slot_id"] == slot_id
        )
        artifact_id = f"external__{scenario_slot}__{kind}"
        validate_revealed_external_artifact(
            artifact_id,
            self.external_contents[artifact_id],
            manifest=self.assembled.manifest,
            attestation=self.attestation,
            authority=authority,
            slot_id=slot_id,
            attempt_no=attempt_no,
        )

    def prepare_attempt_for_output(
        self,
        authority: RevealAuthority,
        slot_id: str,
        attempt_no: int,
    ) -> None:
        authority.begin_attempt(slot_id, attempt_no)
        self.reveal_kind(authority, slot_id, attempt_no, "leakage_review")
        scenario_slot = next(
            item["scenario_slot"]
            for item in self.assembled.manifest["execution_order"]
            if item["slot_id"] == slot_id
        )
        scenario = next(
            item
            for item in self.assembled.manifest["evidence_scenarios"]
            if item["scenario_slot"] == scenario_slot
        )
        if scenario["evidence_class"] == "blind_holdout":
            for kind in ("fixture", "source_ledger", "model_visible_snapshot"):
                self.reveal_kind(authority, slot_id, attempt_no, kind)

    def authority(self) -> RevealAuthority:
        registry = self.registered_registry()
        return RevealAuthority(
            self.assembled.manifest,
            self.manifest_hash,
            self.attestation,
            artifact_bytes=self.assembled.artifact_bytes,
            registry=registry,
            registration_receipt=self.registration_receipt(),
        )

    def test_reveal_authority_requires_registered_manifest_and_receipt(self) -> None:
        with self.assertRaisesRegex(ValueError, "invalid_manifest_binding"):
            RevealAuthority(
                self.assembled.manifest,
                self.manifest_hash,
                self.attestation,
                artifact_bytes=self.assembled.artifact_bytes,
                registry=InMemoryManifestRegistry(),
                registration_receipt=self.registration_receipt(),
            )

    def test_reveal_authority_rejects_seed_and_attestation_outside_registration(
        self,
    ) -> None:
        substituted_seed = copy.deepcopy(self.seed)
        substituted_seed["created_at"] = "2026-07-14T23:59:59Z"
        substituted_attestation = copy.deepcopy(self.attestation)
        substituted_attestation["review_seed_sha256"] = review_json_sha256(
            substituted_seed
        )
        artifacts = dict(self.assembled.artifact_bytes)
        artifacts["evaluation_review_seed"] = canonicalize_review_json(
            substituted_seed
        )
        artifacts["external_review_attestation"] = canonicalize_review_json(
            substituted_attestation
        )
        receipt = self.registration_receipt()
        receipt["review_seed_sha256"] = review_json_sha256(substituted_seed)
        receipt["review_attestation_sha256"] = review_json_sha256(
            substituted_attestation
        )
        with self.assertRaisesRegex(ValueError, "invalid_manifest_binding"):
            RevealAuthority(
                self.assembled.manifest,
                self.manifest_hash,
                substituted_attestation,
                artifact_bytes=artifacts,
                registry=self.registered_registry(),
                registration_receipt=receipt,
            )

    def test_reveal_authority_owns_immutable_manifest_and_attestation_snapshots(
        self,
    ) -> None:
        manifest = copy.deepcopy(self.assembled.manifest)
        attestation = copy.deepcopy(self.attestation)
        authority = RevealAuthority(
            manifest,
            self.manifest_hash,
            attestation,
            artifact_bytes=self.assembled.artifact_bytes,
            registry=self.registered_registry(),
            registration_receipt=self.registration_receipt(),
        )
        manifest["scenario_slots"].reverse()
        attestation["external_artifacts"][0]["content_sha256"] = "0" * 64
        self.assertEqual(
            self.assembled.manifest["scenario_slots"],
            authority.manifest["scenario_slots"],
        )
        self.assertEqual(
            self.attestation["external_artifacts"][0]["content_sha256"],
            authority.attestation["external_artifacts"][0]["content_sha256"],
        )

    def test_reveal_authority_public_snapshots_are_defensive_copies(self) -> None:
        authority = self.authority()
        manifest_view = authority.manifest
        attestation_view = authority.attestation

        manifest_view["scenario_slots"].reverse()
        attestation_view["external_artifacts"][0]["content_sha256"] = "0" * 64

        self.assertEqual(
            self.assembled.manifest["scenario_slots"],
            authority.manifest["scenario_slots"],
        )
        self.assertEqual(
            self.attestation["external_artifacts"][0]["content_sha256"],
            authority.attestation["external_artifacts"][0]["content_sha256"],
        )

    def test_reveal_authority_public_snapshots_cannot_be_replaced(self) -> None:
        authority = self.authority()

        with self.assertRaises(AttributeError):
            authority.manifest = {}
        with self.assertRaises(AttributeError):
            authority.attestation = {}

    def test_reveal_rejects_caller_attestation_drift(self) -> None:
        authority = self.authority()
        slot_id = "slot_projectodyssey_raw_full_history_1"
        authority.begin_attempt(slot_id, 1)
        artifact_id = "external__projectodyssey__leakage_review"
        substituted = copy.deepcopy(self.attestation)
        substituted["reviewer_id"] = "substituted_reviewer"
        with self.assertRaisesRegex(ValueError, "invalid_manifest_binding"):
            validate_revealed_external_artifact(
                artifact_id,
                self.external_contents[artifact_id],
                manifest=self.assembled.manifest,
                attestation=substituted,
                authority=authority,
                slot_id=slot_id,
                attempt_no=1,
            )

    def test_b8_reveal_hash_and_length_are_verified_at_phase(self) -> None:
        authority = self.authority()
        slot_id = "slot_blind_holdout_a_raw_full_history_1"
        authority.begin_attempt(slot_id, 1)
        self.reveal_kind(authority, slot_id, 1, "leakage_review")
        artifact_id = "external__blind_holdout_a__fixture"
        payload = self.external_contents[artifact_id]
        revealed = validate_revealed_external_artifact(
            artifact_id,
            payload,
            manifest=self.assembled.manifest,
            attestation=self.attestation,
            authority=authority,
            slot_id=slot_id,
            attempt_no=1,
        )
        self.assertEqual("fixture", revealed["purpose"])
        with self.assertRaisesRegex(ValueError, "external_artifact_content_mismatch"):
            validate_revealed_external_artifact(
                artifact_id,
                payload + b" ",
                manifest=self.assembled.manifest,
                attestation=self.attestation,
                authority=authority,
                slot_id=slot_id,
                attempt_no=1,
            )

    def test_b14_phase_is_scoped_by_manifest_slot_and_attempt(self) -> None:
        authority = self.authority()
        slot_a = "slot_blind_holdout_a_raw_full_history_1"
        slot_b = "slot_blind_holdout_a_semantic_rerank_1"
        self.prepare_attempt_for_output(authority, slot_a, 1)
        authority.begin_attempt(slot_b, 1)
        authority.fix_model_output(slot_a, 1, output_sha256="a" * 64, patch_sha256="b" * 64)
        hidden_id = "external__blind_holdout_a__hidden_test_bundle"
        validate_revealed_external_artifact(
            hidden_id,
            self.external_contents[hidden_id],
            manifest=self.assembled.manifest,
            attestation=self.attestation,
            authority=authority,
            slot_id=slot_a,
            attempt_no=1,
        )
        with self.assertRaisesRegex(ValueError, "invalid_reveal_phase"):
            validate_revealed_external_artifact(
                hidden_id,
                self.external_contents[hidden_id],
                manifest=self.assembled.manifest,
                attestation=self.attestation,
                authority=authority,
                slot_id=slot_b,
                attempt_no=1,
            )
        authority.bind_extraction_root(slot_a, 1, "/tmp/evaluator-a")
        authority.destroy_extraction_root(slot_a, 1, "/tmp/evaluator-a")
        with self.assertRaisesRegex(ValueError, "invalid_reveal_phase"):
            authority.authorize_provider_action(slot_a, 1, extraction_root="/tmp/evaluator-a")
        with self.assertRaisesRegex(ValueError, "invalid_reveal_phase"):
            authority.authorize_provider_action(slot_b, 1, extraction_root="/tmp/evaluator-a")

    def test_b15_label_barrier_requires_all_scenario_outputs_immutable(self) -> None:
        authority = self.authority()
        scenario = "projectodyssey"
        slots = [
            item["slot_id"]
            for item in self.assembled.manifest["execution_order"]
            if item["scenario_slot"] == scenario
        ]
        for slot_id in slots[:-1]:
            self.prepare_attempt_for_output(authority, slot_id, 1)
            authority.fix_model_output(slot_id, 1, output_sha256="a" * 64, patch_sha256="b" * 64)
        with self.assertRaisesRegex(ValueError, "invalid_reveal_phase"):
            authority.close_scenario_outputs(scenario)
        self.prepare_attempt_for_output(authority, slots[-1], 1)
        authority.fix_model_output(slots[-1], 1, output_sha256="c" * 64, patch_sha256="d" * 64)
        authority.close_scenario_outputs(scenario)
        artifact_id = "external__projectodyssey__required_memory_label_ledger"
        validate_revealed_external_artifact(
            artifact_id,
            self.external_contents[artifact_id],
            manifest=self.assembled.manifest,
            attestation=self.attestation,
            authority=authority,
            slot_id=slots[-1],
            attempt_no=1,
        )
        with self.assertRaisesRegex(ValueError, "invalid_reveal_phase"):
            authority.authorize_provider_action(slots[-1], 1)

    def test_public_reveal_entry_cannot_mutate_attested_label_binding(self) -> None:
        authority = self.authority()
        scenario = "projectodyssey"
        slots = [
            item["slot_id"]
            for item in self.assembled.manifest["execution_order"]
            if item["scenario_slot"] == scenario
        ]
        for slot_id in slots:
            self.prepare_attempt_for_output(authority, slot_id, 1)
            authority.fix_model_output(
                slot_id,
                1,
                output_sha256="a" * 64,
                patch_sha256="b" * 64,
            )
        authority.close_scenario_outputs(scenario)

        slot_id = slots[-1]
        artifact_id = "external__projectodyssey__required_memory_label_ledger"
        attested_payload = self.external_contents[artifact_id]
        substituted = json.loads(attested_payload)
        registered_refs = set(substituted["required_source_refs"])
        source_ledger = authority.source_ledger(slot_id, 1)
        self.assertIsNotNone(source_ledger)
        ledger_refs = [entry["source_ref"] for entry in source_ledger["entries"]]
        replacement_refs = [ref for ref in ledger_refs if ref not in registered_refs]
        self.assertTrue(replacement_refs)
        substituted["required_source_refs"] = [replacement_refs[0]]
        substituted_payload = canonicalize_review_json(substituted)
        self.assertNotEqual(attested_payload, substituted_payload)
        self.assertIn(substituted["required_source_refs"][0], ledger_refs)
        self.assertNotIn(substituted["required_source_refs"][0], registered_refs)

        public_entry = authority.assert_reveal_allowed(artifact_id, slot_id, 1)
        public_entry["content_sha256"] = hashlib.sha256(
            substituted_payload
        ).hexdigest()
        public_entry["byte_length"] = len(substituted_payload)

        with self.assertRaisesRegex(
            ValueError,
            "revealed bytes do not match the attested length and digest",
        ):
            validate_revealed_external_artifact(
                artifact_id,
                substituted_payload,
                manifest=authority.manifest,
                attestation=authority.attestation,
                authority=authority,
                slot_id=slot_id,
                attempt_no=1,
            )

    def test_provider_action_requires_pre_output_reveals_and_open_attempt(self) -> None:
        authority = self.authority()
        slot_id = "slot_blind_holdout_a_raw_full_history_1"
        authority.begin_attempt(slot_id, 1)
        with self.assertRaisesRegex(ValueError, "invalid_reveal_phase"):
            authority.authorize_provider_action(slot_id, 1)
        self.reveal_kind(authority, slot_id, 1, "leakage_review")
        with self.assertRaisesRegex(ValueError, "invalid_reveal_phase"):
            authority.authorize_provider_action(slot_id, 1)
        for kind in ("fixture", "source_ledger", "model_visible_snapshot"):
            self.reveal_kind(authority, slot_id, 1, kind)
        authority.authorize_provider_action(slot_id, 1)
        authority.fix_model_output(
            slot_id,
            1,
            output_sha256="a" * 64,
            patch_sha256="b" * 64,
        )
        with self.assertRaisesRegex(ValueError, "invalid_reveal_phase"):
            authority.authorize_provider_action(slot_id, 1)

    def test_b15_label_barrier_rejects_a_mutable_retry_attempt(self) -> None:
        authority = self.authority()
        scenario = "projectodyssey"
        slots = [
            item["slot_id"]
            for item in self.assembled.manifest["execution_order"]
            if item["scenario_slot"] == scenario
        ]
        for slot_id in slots:
            self.prepare_attempt_for_output(authority, slot_id, 1)
            authority.fix_model_output(
                slot_id,
                1,
                output_sha256="a" * 64,
                patch_sha256="b" * 64,
            )
        authority.begin_attempt(slots[0], 2)
        with self.assertRaisesRegex(ValueError, "invalid_reveal_phase"):
            authority.close_scenario_outputs(scenario)

    def test_reveal_automaton_rejects_skipped_and_backward_phases(self) -> None:
        authority = self.authority()
        slot_id = "slot_blind_holdout_a_raw_full_history_1"
        authority.begin_attempt(slot_id, 1)
        with self.assertRaisesRegex(ValueError, "invalid_reveal_phase"):
            self.reveal_kind(authority, slot_id, 1, "fixture")
        with self.assertRaisesRegex(ValueError, "invalid_reveal_phase"):
            authority.fix_model_output(
                slot_id,
                1,
                output_sha256="a" * 64,
                patch_sha256="b" * 64,
            )
        self.reveal_kind(authority, slot_id, 1, "leakage_review")
        for kind in ("fixture", "source_ledger", "model_visible_snapshot"):
            self.reveal_kind(authority, slot_id, 1, kind)
        authority.fix_model_output(
            slot_id,
            1,
            output_sha256="a" * 64,
            patch_sha256="b" * 64,
        )
        with self.assertRaisesRegex(ValueError, "invalid_reveal_phase"):
            self.reveal_kind(authority, slot_id, 1, "leakage_review")

    def test_closed_scenario_cannot_open_a_new_attempt(self) -> None:
        authority = self.authority()
        scenario = "projectodyssey"
        slots = [
            item["slot_id"]
            for item in self.assembled.manifest["execution_order"]
            if item["scenario_slot"] == scenario
        ]
        for slot_id in slots:
            self.prepare_attempt_for_output(authority, slot_id, 1)
            authority.fix_model_output(
                slot_id,
                1,
                output_sha256="a" * 64,
                patch_sha256="b" * 64,
            )
        authority.close_scenario_outputs(scenario)
        with self.assertRaisesRegex(ValueError, "invalid_reveal_phase"):
            authority.begin_attempt(slots[0], 2)

    def test_b17_bundle_kind_purpose_dispatch_precedes_entry_decode(self) -> None:
        invalid = deterministic_bundle("blind_holdout_a", "hidden_tests", {"x.py": b"x"})
        invalid["files"][0]["content_base64"] = "not base64"
        with tempfile.TemporaryDirectory() as root:
            with self.assertRaisesRegex(ValueError, "external_artifact_content_mismatch /purpose"):
                materialize_validated_bundle(
                    invalid,
                    expected_purpose="fixture",
                    destination_root=Path(root),
                    evaluator_owned_root=Path(root),
                )

    def test_bundle_bytes_must_be_rfc8785_canonical_before_materialization(self) -> None:
        bundle = deterministic_bundle(
            "blind_holdout_a",
            "fixture",
            {"safe.py": b"safe"},
        )
        noncanonical = json.dumps(bundle, indent=2).encode("utf-8")
        with tempfile.TemporaryDirectory() as root:
            with self.assertRaisesRegex(
                ValueError,
                "external_artifact_content_mismatch",
            ):
                materialize_validated_bundle(
                    noncanonical,
                    expected_purpose="fixture",
                    destination_root=Path(root),
                    evaluator_owned_root=Path(root),
                )
            self.assertEqual([], list(Path(root).iterdir()))

    def test_b22_bundle_paths_fail_before_decode_or_write(self) -> None:
        bad_paths = [".", "..", "", "a//b", "/a", "a/", "é.py", "A/x.py"]
        for path in bad_paths:
            with self.subTest(path=path):
                bundle = deterministic_bundle("blind_holdout_a", "fixture", {"safe.py": b"safe"})
                bundle["files"][0]["path"] = path
                bundle["files"][0]["content_base64"] = "not base64"
                if path == "A/x.py":
                    bundle["files"].append(copy.deepcopy(bundle["files"][0]))
                    bundle["files"][0]["path"] = "a/x.py"
                    bundle["files"][1]["path"] = "A/x.py"
                with tempfile.TemporaryDirectory() as root:
                    with self.assertRaisesRegex(ValueError, "invalid_bundle_path"):
                        materialize_validated_bundle(
                            bundle,
                            expected_purpose="fixture",
                            destination_root=Path(root),
                            evaluator_owned_root=Path(root),
                        )
                    self.assertEqual([], list(Path(root).iterdir()))

    def test_b22_symlinked_materialization_root_is_rejected(self) -> None:
        bundle = deterministic_bundle("blind_holdout_a", "fixture", {"safe.py": b"safe"})
        with tempfile.TemporaryDirectory() as parent:
            parent_path = Path(parent)
            owned = parent_path / "owned"
            owned.mkdir()
            alias = parent_path / "alias"
            alias.symlink_to(owned, target_is_directory=True)
            with self.assertRaisesRegex(ValueError, "invalid_bundle_path"):
                materialize_validated_bundle(
                    bundle,
                    expected_purpose="fixture",
                    destination_root=alias,
                    evaluator_owned_root=owned,
                )
            self.assertEqual([], list(owned.iterdir()))

    def test_materialization_requires_an_empty_disposable_root(self) -> None:
        bundle = deterministic_bundle(
            "blind_holdout_a",
            "fixture",
            {"safe.py": b"safe"},
        )
        with tempfile.TemporaryDirectory() as root:
            root_path = Path(root)
            existing = root_path / "existing.txt"
            existing.write_text("keep", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "invalid_bundle_path"):
                materialize_validated_bundle(
                    bundle,
                    expected_purpose="fixture",
                    destination_root=root_path,
                    evaluator_owned_root=root_path,
                )
            self.assertEqual("keep", existing.read_text(encoding="utf-8"))
            self.assertEqual([existing], list(root_path.iterdir()))

    def test_materialization_writes_verified_files_beneath_root_fd(self) -> None:
        bundle = deterministic_bundle(
            "blind_holdout_a",
            "fixture",
            {"README.md": b"fixture", "src/retry.py": b"def retry(): pass\n"},
        )
        with tempfile.TemporaryDirectory() as root:
            root_path = Path(root)
            written = materialize_validated_bundle(
                bundle,
                expected_purpose="fixture",
                destination_root=root_path,
                evaluator_owned_root=root_path,
            )
            self.assertEqual(
                [
                    root_path.resolve() / "README.md",
                    root_path.resolve() / "src/retry.py",
                ],
                written,
            )
            self.assertEqual("fixture", written[0].read_text(encoding="utf-8"))
            self.assertEqual(
                "def retry(): pass\n",
                written[1].read_text(encoding="utf-8"),
            )

    def test_hidden_bundle_materialization_is_attempt_phase_scoped(self) -> None:
        authority = self.authority()
        slot_id = "slot_blind_holdout_a_raw_full_history_1"
        artifact_id = "external__blind_holdout_a__hidden_test_bundle"
        payload = self.external_contents[artifact_id]
        authority.begin_attempt(slot_id, 1)
        with tempfile.TemporaryDirectory() as root:
            with self.assertRaisesRegex(ValueError, "invalid_reveal_phase"):
                materialize_deterministic_bundle(
                    artifact_id,
                    payload,
                    authority=authority,
                    slot_id=slot_id,
                    attempt_no=1,
                    destination_root=Path(root),
                    evaluator_owned_root=Path(root),
                )
            self.assertEqual([], list(Path(root).iterdir()))

        self.reveal_kind(authority, slot_id, 1, "leakage_review")
        for kind in ("fixture", "source_ledger", "model_visible_snapshot"):
            self.reveal_kind(authority, slot_id, 1, kind)
        authority.fix_model_output(
            slot_id,
            1,
            output_sha256="a" * 64,
            patch_sha256="b" * 64,
        )
        with tempfile.TemporaryDirectory() as root:
            root_path = Path(root)
            written = materialize_deterministic_bundle(
                artifact_id,
                payload,
                authority=authority,
                slot_id=slot_id,
                attempt_no=1,
                destination_root=root_path,
                evaluator_owned_root=root_path,
            )
            self.assertEqual(1, len(written))
            self.assertEqual("test_retry.py", written[0].name)
            with self.assertRaisesRegex(ValueError, "invalid_reveal_phase"):
                authority.authorize_provider_action(slot_id, 1)
            authority.destroy_extraction_root(
                slot_id,
                1,
                str(root_path.resolve()),
            )
            with self.assertRaisesRegex(ValueError, "invalid_reveal_phase"):
                authority.authorize_provider_action(slot_id, 1)
            with self.assertRaisesRegex(ValueError, "invalid_reveal_phase"):
                authority.authorize_provider_action(
                    slot_id,
                    1,
                    extraction_root=str(root_path.resolve()),
                )

    def test_active_hidden_root_blocks_provider_action_in_another_attempt(self) -> None:
        authority = self.authority()
        first_slot = "slot_blind_holdout_a_raw_full_history_1"
        second_slot = "slot_blind_holdout_a_semantic_rerank_1"
        self.prepare_attempt_for_output(authority, first_slot, 1)
        authority.fix_model_output(
            first_slot,
            1,
            output_sha256="a" * 64,
            patch_sha256="b" * 64,
        )
        self.prepare_attempt_for_output(authority, second_slot, 1)
        artifact_id = "external__blind_holdout_a__hidden_test_bundle"
        with tempfile.TemporaryDirectory() as root:
            root_path = Path(root)
            materialize_deterministic_bundle(
                artifact_id,
                self.external_contents[artifact_id],
                authority=authority,
                slot_id=first_slot,
                attempt_no=1,
                destination_root=root_path,
                evaluator_owned_root=root_path,
            )
            with self.assertRaisesRegex(ValueError, "invalid_reveal_phase"):
                authority.authorize_provider_action(second_slot, 1)
            authority.destroy_extraction_root(
                first_slot,
                1,
                str(root_path.resolve()),
            )
            authority.authorize_provider_action(second_slot, 1)

    def test_b20_cell_input_authority_is_scenario_local(self) -> None:
        inputs = resolve_execution_cell_inputs(self.assembled.manifest, "projectodyssey")
        self.assertEqual("repo_projectodyssey", inputs.repository_snapshot_artifact_id)
        self.assertEqual("snapshot_projectodyssey", inputs.model_visible_snapshot_artifact_id)
        mutated = copy.deepcopy(self.assembled.manifest)
        mutated["comparison_contract"]["repository_snapshot_artifact_id"] = "forged"
        with self.assertRaisesRegex(ValueError, "invalid_review_seed"):
            resolve_execution_cell_inputs(mutated, "projectodyssey")
        blind = copy.deepcopy(self.assembled.manifest)
        blind_scenario = next(
            item for item in blind["evidence_scenarios"] if item["evidence_class"] == "blind_holdout"
        )
        blind_scenario["repository_snapshot_artifact_id"] = "forged"
        with self.assertRaisesRegex(ValueError, "invalid_scenario_identity"):
            resolve_execution_cell_inputs(blind, blind_scenario["scenario_slot"])

    def test_b9_manifest_dispatcher_is_disjoint(self) -> None:
        floor = build_floor_execution_manifest()
        self.assertEqual([], list(manifest_validator().iter_errors(floor)))
        legacy_full = copy.deepcopy(floor)
        legacy_full["descope_rung"] = "Full"
        self.assertTrue(list(manifest_validator().iter_errors(legacy_full)))
        self.assertEqual([], list(manifest_validator().iter_errors(self.assembled.manifest)))
        invalid_41_floor = copy.deepcopy(self.assembled.manifest)
        invalid_41_floor["descope_rung"] = "Floor"
        self.assertTrue(list(manifest_validator().iter_errors(invalid_41_floor)))

    def test_b9_legacy_non_floor_is_only_accepted_by_diagnostic_parser(self) -> None:
        source_ledgers = build_source_ledgers()
        relation_ledgers = build_relation_label_ledgers(source_ledgers)
        holdout = build_simulated_external_holdout_bundle()
        manifest = build_full_execution_manifest(
            source_ledgers=source_ledgers,
            relation_label_ledgers=relation_ledgers,
            simulated_external_holdout=holdout,
        )
        all_ledgers = {
            **source_ledgers,
            holdout["scenario_slot"]: holdout["source_ledger"],
        }
        artifacts = build_execution_input_artifact_bytes(
            manifest,
            source_ledgers=all_ledgers,
            simulated_external_holdout=holdout,
        )
        with self.assertRaisesRegex(ValueError, "legacy_non_floor_diagnostic_only"):
            validate_execution_manifest(
                manifest,
                artifact_bytes=artifacts,
                source_ledgers=all_ledgers,
            )
        validate_legacy_execution_manifest_diagnostic(
            manifest,
            artifact_bytes=artifacts,
            source_ledgers=all_ledgers,
        )

    def test_b10_descendants_bind_registered_final_hash_and_rules(self) -> None:
        self.assertIn("semantic_rules_version", SCHEMA["$defs"]["run"]["required"])
        self.assertIn("semantic_rules_version", SCHEMA["$defs"]["aggregate"]["required"])
        registry = self.registered_registry()
        descendant = {
            "semantic_rules_version": "4.1",
            "execution_manifest_sha256": self.manifest_hash,
        }
        validate_descendant_binding(descendant, self.assembled.manifest, registry)
        for field, value in (
            ("semantic_rules_version", "4.0"),
            ("execution_manifest_sha256", self.seed_hash),
        ):
            mutated = dict(descendant)
            mutated[field] = value
            with self.assertRaisesRegex(ValueError, "invalid_manifest_binding"):
                validate_descendant_binding(mutated, self.assembled.manifest, registry)
        class ForgedRegistry:
            def resolve(self, _seed_hash):
                return self.manifest_hash

        forged = ForgedRegistry()
        forged.manifest_hash = self.manifest_hash
        with self.assertRaisesRegex(ValueError, "invalid_manifest_binding"):
            validate_descendant_binding(
                descendant,
                self.assembled.manifest,
                forged,
            )

    def test_b10_run_validator_requires_registered_final_manifest(self) -> None:
        run = build_evaluation_run(self.assembled.manifest)
        artifacts = {
            **self.assembled.artifact_bytes,
            **build_run_output_artifact_bytes(),
        }
        scenario = next(
            item
            for item in self.seed["scenario_plan"]
            if item["scenario_slot"] == run["scenario_id"]
        )
        source_ledger = json.loads(
            self.seed_artifacts[scenario["source_ledger_artifact_id"]]
        )
        with self.assertRaisesRegex(ValueError, "invalid_manifest_binding"):
            validate_evaluation_run(
                run,
                self.assembled.manifest,
                artifact_bytes=artifacts,
                source_ledger=source_ledger,
            )
        registry = self.registered_registry()
        validate_evaluation_run(
            run,
            self.assembled.manifest,
            artifact_bytes=artifacts,
            source_ledger=source_ledger,
            manifest_registry=registry,
        )

    def test_b10_aggregate_and_evidence_validators_require_registered_manifest(self) -> None:
        relations = {
            scenario["scenario_slot"]: json.loads(
                self.external_contents[
                    f"external__{scenario['scenario_slot']}__relation_label_ledger"
                ]
            )
            for scenario in self.seed["scenario_plan"]
        }
        ledgers = {}
        for scenario in self.seed["scenario_plan"]:
            slot = scenario["scenario_slot"]
            payload = (
                self.seed_artifacts[scenario["source_ledger_artifact_id"]]
                if scenario["evidence_class"] == "source_backed_synthetic"
                else self.external_contents[f"external__{slot}__source_ledger"]
            )
            ledgers[slot] = json.loads(payload)
        runs = []
        for slot in self.assembled.manifest["execution_order"]:
            relation_opportunities = (
                _relation_opportunities_for_ledger(
                    slot["scenario_slot"],
                    relations[slot["scenario_slot"]],
                )
                if slot["variant_id"] == "recallpack"
                else []
            )
            runs.append(
                build_evaluation_run(
                    self.assembled.manifest,
                    run_id=f"eval_{slot['slot_index']}",
                    scenario_id=slot["scenario_slot"],
                    variant_id=slot["variant_id"],
                    slot_index=slot["slot_index"],
                    attempt_no=slot["repetition"],
                    relation_opportunities=relation_opportunities,
                )
            )
        aggregate = build_aggregate_report(
            self.assembled.manifest,
            run_records=runs,
            n=len(runs),
            numerator=len(runs),
            denominator=len(runs),
        )
        artifacts = {
            **self.assembled.artifact_bytes,
            **build_run_output_artifact_bytes(),
        }
        for run in runs:
            artifacts[f"run_{run['run_id']}"] = canonicalize_review_json(run)
        loader = build_test_only_retained_attempt_loader(
            self.assembled.manifest,
            runs,
        )
        kwargs = {
            "execution_manifest": self.assembled.manifest,
            "retained_attempt_loader": loader,
            "artifact_bytes": artifacts,
            "source_ledgers": ledgers,
            "relation_label_ledgers": relations,
        }
        with self.assertRaisesRegex(ValueError, "invalid_manifest_binding"):
            validate_aggregate_report(aggregate, **kwargs)
        evidence = build_evidence_manifest(
            self.assembled.manifest,
            run_records=runs,
            aggregate_records=[aggregate],
        )
        with self.assertRaisesRegex(ValueError, "invalid_manifest_binding"):
            validate_evidence_manifest(
                evidence,
                self.assembled.manifest,
                retained_attempt_loader=loader,
                artifact_bytes=artifacts,
                source_ledgers=ledgers,
                relation_label_ledgers=relations,
            )

    def test_b12_registration_receipt_binds_chronology_and_all_hashes(self) -> None:
        registry = self.registered_registry()
        receipt = {
            "record_type": "manifest_registration_receipt",
            "receipt_version": "review-receipt/4.1",
            "sequence": 2,
            "receipt_id": "manifest_receipt_test",
            "review_seed_sha256": self.seed_hash,
            "review_attestation_sha256": review_json_sha256(self.attestation),
            "execution_manifest_sha256": self.manifest_hash,
            "registered_at": "2026-07-15T00:03:00Z",
            "registrar_role": "user-custodian",
            "assurance": "procedural",
        }
        validate_manifest_registration_receipt(
            receipt,
            seed=self.seed,
            attestation=self.attestation,
            manifest=self.assembled.manifest,
            registry=registry,
        )
        receipt["registered_at"] = "2026-07-14T00:00:00Z"
        with self.assertRaisesRegex(ValueError, "invalid_review_attestation"):
            validate_manifest_registration_receipt(
                receipt,
                seed=self.seed,
                attestation=self.attestation,
                manifest=self.assembled.manifest,
                registry=registry,
            )


if __name__ == "__main__":
    unittest.main()
