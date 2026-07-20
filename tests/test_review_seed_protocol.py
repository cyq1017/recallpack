from __future__ import annotations

import copy
import json
import tempfile
import unittest
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker

from recallpack.evidence import (
    InMemoryManifestRegistry,
    SqliteManifestRegistry,
    assemble_execution_manifest_41,
    canonicalize_review_json,
    compute_frozen_code_hashes,
    derive_external_artifact_slots,
    parse_review_json,
    register_execution_manifest_41,
    review_json_sha256,
    validate_evaluation_review_seed,
    validate_execution_manifest,
    validate_execution_manifest_41,
    validate_external_review_attestation,
)
from tests._v41_review_seed_fixtures import (
    build_attestation,
    build_r2_seed,
    canonical_bytes,
    materialize_frozen_code_repository,
)


ROOT = Path(__file__).resolve().parents[1]
SCHEMA_PATH = ROOT / "specs/001-recallpack-v4/contracts/evaluation.schema.json"


class ReviewSeedProtocolTests(unittest.TestCase):
    def setUp(self) -> None:
        self.seed, self.artifact_bytes = build_r2_seed()
        self._repository = tempfile.TemporaryDirectory()
        self.addCleanup(self._repository.cleanup)
        self.repository_root = Path(self._repository.name)
        materialize_frozen_code_repository(
            self.repository_root,
            SCHEMA_PATH.read_bytes(),
        )
        self.seed["code_hashes"] = compute_frozen_code_hashes(self.repository_root)

    def test_b1_schema_is_integrated_and_accepts_r2_seed(self) -> None:
        schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
        self.assertIn("evaluationReviewSeed", schema["$defs"])
        validator = Draft202012Validator(
            {
                "$schema": schema["$schema"],
                "$defs": schema["$defs"],
                "$ref": "#/$defs/evaluationReviewSeed",
            },
            format_checker=FormatChecker(),
        )
        self.assertEqual([], list(validator.iter_errors(self.seed)))

    def test_b1_jcs_golden_and_rejection_vectors(self) -> None:
        value = {"z": -0.0, "a": [1e-7, 1e-6, 1e20, 1e21], "€": "\u20ac"}
        expected = '{"a":[1e-7,0.000001,100000000000000000000,1e+21],"z":0,"€":"€"}'
        self.assertEqual(expected.encode(), canonicalize_review_json(value))
        self.assertEqual(value, parse_review_json(canonicalize_review_json(value)))
        with self.assertRaisesRegex(ValueError, "invalid_review_json"):
            parse_review_json(b'{"a":1,"a":2}')
        with self.assertRaisesRegex(ValueError, "invalid_review_json"):
            parse_review_json(b'"\\ud800"')
        with self.assertRaisesRegex(ValueError, "invalid_review_json"):
            parse_review_json(b'{"x":NaN}')
        for value in (1 << 53, -(1 << 53)):
            with self.subTest(value=value):
                with self.assertRaisesRegex(ValueError, "invalid_review_json"):
                    canonicalize_review_json({"value": value})
        with self.assertRaisesRegex(ValueError, "invalid_review_json"):
            parse_review_json(b'{"value":1152921504606846976}')
        stable_large_float = parse_review_json(b'{"value":100000000000000000000}')
        self.assertEqual(
            b'{"value":100000000000000000000}',
            canonicalize_review_json(stable_large_float),
        )

    def test_registration_requires_live_repository_code_hash_binding(self) -> None:
        seed_hash = review_json_sha256(self.seed)
        attestation, receipt = build_attestation(self.seed, seed_hash)
        assembled = assemble_execution_manifest_41(
            self.seed,
            attestation,
            seed_receipt=receipt,
            artifact_bytes=self.artifact_bytes,
            repository_root=self.repository_root,
        )
        with self.assertRaisesRegex(ValueError, "invalid_review_seed /code_hashes"):
            validate_execution_manifest_41(
                assembled.manifest,
                artifact_bytes=assembled.artifact_bytes,
            )
        forged_root = self.repository_root / "forged"
        materialize_frozen_code_repository(forged_root, SCHEMA_PATH.read_bytes())
        (forged_root / "src/recallpack/runtime.py").write_text("RUNTIME = 'forged'\n")
        with self.assertRaisesRegex(ValueError, "invalid_review_seed /code_hashes"):
            validate_execution_manifest_41(
                assembled.manifest,
                artifact_bytes=assembled.artifact_bytes,
                repository_root=forged_root,
            )
        validate_execution_manifest_41(
            assembled.manifest,
            artifact_bytes=assembled.artifact_bytes,
            repository_root=self.repository_root,
        )

    def test_b2_seed_validates_and_mutation_fails_closed(self) -> None:
        validate_evaluation_review_seed(self.seed, artifact_bytes=self.artifact_bytes)
        mutated = copy.deepcopy(self.seed)
        mutated["comparison_contract"]["budget_tokens"] = 511
        with self.assertRaisesRegex(ValueError, "invalid_review_seed"):
            validate_evaluation_review_seed(
                mutated,
                artifact_bytes=self.artifact_bytes,
            )

    def test_41_grid_provider_artifact_image_and_claim_semantics_fail_closed(self) -> None:
        mutations: list[tuple[str, dict]] = []

        duplicate_slot_id = copy.deepcopy(self.seed)
        duplicate_slot_id["execution_order"][1]["slot_id"] = duplicate_slot_id[
            "execution_order"
        ][0]["slot_id"]
        mutations.append(("duplicate_slot_id", duplicate_slot_id))

        duplicate_slot_index = copy.deepcopy(self.seed)
        duplicate_slot_index["execution_order"][1]["slot_index"] = 0
        mutations.append(("duplicate_slot_index", duplicate_slot_index))

        broken_grid = copy.deepcopy(self.seed)
        broken_grid["execution_order"][2]["repetition"] = 2
        mutations.append(("broken_grid", broken_grid))

        forged_model = copy.deepcopy(self.seed)
        forged_model["provider_settings"]["models"][
            "memory_decision"
        ] = "forged-model-id"
        mutations.append(("forged_model", forged_model))

        wrong_artifact_kind = copy.deepcopy(self.seed)
        wrong_artifact_kind["frozen_input_artifact_catalog"]["patch_contract"][
            "kind"
        ] = "prompt_template"
        mutations.append(("wrong_artifact_kind", wrong_artifact_kind))

        broken_image_binding = copy.deepcopy(self.seed)
        broken_image_binding["evaluator_contract"]["image_digest"] = "sha256:" + "a1" * 32
        broken_image_binding["evaluator_image_digest"] = "sha256:" + "a1" * 32
        mutations.append(("broken_image_binding", broken_image_binding))

        duplicate_claim = copy.deepcopy(self.seed)
        duplicate_claim["claim_declarations"].append(
            copy.deepcopy(duplicate_claim["claim_declarations"][0])
        )
        mutations.append(("duplicate_claim", duplicate_claim))

        for name, mutated in mutations:
            with self.subTest(name=name):
                with self.assertRaisesRegex(ValueError, "invalid_review_seed"):
                    validate_evaluation_review_seed(
                        mutated,
                        artifact_bytes=self.artifact_bytes,
                    )

    def test_b4_external_slots_are_validator_derived(self) -> None:
        self.assertEqual(
            self.seed["external_artifact_slots"],
            derive_external_artifact_slots(self.seed),
        )
        mutated = copy.deepcopy(self.seed)
        mutated["external_artifact_slots"][0]["reveal_phase"] = "before_scenario_execution"
        with self.assertRaisesRegex(ValueError, "external_artifact_set_mismatch"):
            validate_evaluation_review_seed(
                mutated,
                artifact_bytes=self.artifact_bytes,
            )

    def test_b5_attestation_binds_seed_receipt_and_exact_slots(self) -> None:
        seed_hash = review_json_sha256(self.seed)
        attestation, receipt = build_attestation(self.seed, seed_hash)
        validate_external_review_attestation(attestation, self.seed, receipt)
        mutated = copy.deepcopy(attestation)
        mutated["external_artifacts"][0]["scenario_slot"] = "deepagents"
        with self.assertRaisesRegex(ValueError, "invalid_review_attestation"):
            validate_external_review_attestation(mutated, self.seed, receipt)

    def test_b6_repeated_character_sentinel_digest_is_rejected(self) -> None:
        seed_hash = review_json_sha256(self.seed)
        attestation, receipt = build_attestation(self.seed, seed_hash)
        attestation["external_artifacts"][0]["content_sha256"] = "a" * 64
        with self.assertRaisesRegex(ValueError, "invalid_review_attestation"):
            validate_external_review_attestation(attestation, self.seed, receipt)

    def test_b7_diagnostic_projection_cannot_register(self) -> None:
        seed_hash = review_json_sha256(self.seed)
        attestation, receipt = build_attestation(self.seed, seed_hash)
        assembled = assemble_execution_manifest_41(
            self.seed,
            attestation,
            seed_receipt=receipt,
            artifact_bytes=self.artifact_bytes,
            repository_root=self.repository_root,
        )
        validate_execution_manifest(
            assembled.manifest,
            artifact_bytes=assembled.artifact_bytes,
            repository_root=self.repository_root,
        )
        with self.assertRaisesRegex(ValueError, "invalid_manifest_binding"):
            register_execution_manifest_41(
                assembled.manifest,
                artifact_bytes=assembled.artifact_bytes,
                registry=InMemoryManifestRegistry(),
                seed_receipt=receipt,
                repository_root=self.repository_root,
            )
        forged = copy.deepcopy(assembled.manifest)
        forged["created_at"] = "2026-07-15T00:00:01Z"
        with self.assertRaisesRegex(ValueError, "review_seed_projection_mismatch"):
            validate_execution_manifest_41(
                forged,
                artifact_bytes=assembled.artifact_bytes,
                repository_root=self.repository_root,
            )

    def test_41_r2_freezes_public_scenario_writable_paths(self) -> None:
        seed_hash = review_json_sha256(self.seed)
        attestation, receipt = build_attestation(self.seed, seed_hash)
        assembled = assemble_execution_manifest_41(
            self.seed,
            attestation,
            seed_receipt=receipt,
            artifact_bytes=self.artifact_bytes,
            repository_root=self.repository_root,
        )
        validate_execution_manifest(
            assembled.manifest,
            artifact_bytes=assembled.artifact_bytes,
            repository_root=self.repository_root,
        )
        self.assertEqual(
            [
                "pyproject.toml",
                "src/ci_policy.py",
                "src/package_policy.py",
            ],
            assembled.manifest["comparison_contract"]["writable_paths"],
        )

        stale_demo_paths = copy.deepcopy(self.seed)
        stale_demo_paths["comparison_contract"]["writable_paths"] = [
            "src/retry.py",
            "src/retry_policy.py",
            "src/auth.py",
            "src/config_loader.py",
            "pyproject.toml",
        ]
        with self.assertRaisesRegex(ValueError, "unequal_comparison_contract"):
            validate_evaluation_review_seed(
                stale_demo_paths,
                artifact_bytes=self.artifact_bytes,
            )

    def test_b12_registration_requires_the_attestation_bound_seed_receipt(self) -> None:
        seed_hash = review_json_sha256(self.seed)
        attestation, receipt = build_attestation(self.seed, seed_hash)
        assembled = assemble_execution_manifest_41(
            self.seed,
            attestation,
            seed_receipt=receipt,
            artifact_bytes=self.artifact_bytes,
            repository_root=self.repository_root,
        )
        forged_receipt = copy.deepcopy(receipt)
        forged_receipt["received_at"] = "2026-07-15T00:00:30Z"
        with self.assertRaisesRegex(ValueError, "invalid_review_attestation"):
            assemble_execution_manifest_41(
                self.seed,
                attestation,
                seed_receipt=forged_receipt,
                artifact_bytes=self.artifact_bytes,
                repository_root=self.repository_root,
            )

    def test_b7_legacy_sqlite_rows_never_resolve_as_eligible(self) -> None:
        seed_hash = review_json_sha256(self.seed)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "registrations.sqlite3"
            first = SqliteManifestRegistry(path)
            first._connection.execute(
                "INSERT INTO review_seed_registrations "
                "(review_seed_sha256, execution_manifest_sha256) VALUES (?, ?)",
                (seed_hash, "b" * 64),
            )
            first.close()
            reopened = SqliteManifestRegistry(path)
            self.assertIsNone(reopened.resolve(seed_hash))
            reopened.close()

    def test_b13_comparison_contract_has_no_global_snapshot_authority(self) -> None:
        mutated = copy.deepcopy(self.seed)
        mutated["comparison_contract"]["repository_snapshot_artifact_id"] = "repo"
        with self.assertRaisesRegex(ValueError, "invalid_review_seed"):
            validate_evaluation_review_seed(mutated, artifact_bytes=self.artifact_bytes)

    def test_b19_timestamp_vectors_are_exact_gregorian_utc(self) -> None:
        for timestamp in (
            "0001-01-01T00:00:00Z",
            "2000-02-29T23:59:59Z",
            "9999-12-31T23:59:59Z",
        ):
            seed = copy.deepcopy(self.seed)
            seed["created_at"] = timestamp
            validate_evaluation_review_seed(seed, artifact_bytes=self.artifact_bytes)
        for timestamp in (
            "0000-01-01T00:00:00Z",
            "1900-02-29T00:00:00Z",
            "2026-01-01T00:00:60Z",
            "2026-01-01T00:00:00+00:00",
        ):
            seed = copy.deepcopy(self.seed)
            seed["created_at"] = timestamp
            with self.assertRaisesRegex(ValueError, "invalid_review_seed"):
                validate_evaluation_review_seed(seed, artifact_bytes=self.artifact_bytes)

    def test_b18_manifest_41_has_no_legacy_nested_relation_hash(self) -> None:
        seed_hash = review_json_sha256(self.seed)
        attestation, receipt = build_attestation(self.seed, seed_hash)
        assembled = assemble_execution_manifest_41(
            self.seed,
            attestation,
            seed_receipt=receipt,
            artifact_bytes=self.artifact_bytes,
            repository_root=self.repository_root,
        )
        self.assertNotIn(
            "relation_label_ledger_sha256",
            assembled.manifest["evidence_scenarios"][0],
        )
        slot = assembled.manifest["scenario_slots"][0]
        relation = next(
            item
            for item in attestation["external_artifacts"]
            if item["scenario_slot"] == slot and item["kind"] == "relation_label_ledger"
        )
        self.assertEqual(relation["content_sha256"], assembled.manifest["label_hashes"][slot])

    def test_seed_hash_is_not_legacy_sorted_json_for_negative_zero(self) -> None:
        value = {"value": -0.0}
        self.assertNotEqual(canonical_bytes(value), canonicalize_review_json(value))


if __name__ == "__main__":
    unittest.main()
