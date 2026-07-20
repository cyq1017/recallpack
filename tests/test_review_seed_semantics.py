from __future__ import annotations

import copy
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

from recallpack.evidence import (
    assemble_execution_manifest_41,
    canonicalize_review_json,
    compute_frozen_code_hashes,
    review_json_sha256,
    validate_evaluation_review_seed,
    validate_execution_manifest_41,
    validate_external_review_attestation,
)
from tests._v41_review_seed_fixtures import (
    build_attestation,
    build_full_seed,
    build_r2_seed,
    canonical_bytes,
    materialize_frozen_code_repository,
    sha256_bytes,
)


ROOT = Path(__file__).resolve().parents[1]
VECTORS = ROOT / "specs/001-recallpack-v4/contracts/review-json-golden-vectors.json"


class ReviewSeedSemanticTests(unittest.TestCase):
    def setUp(self) -> None:
        self.seed, self.artifacts = build_r2_seed()
        self._repository = tempfile.TemporaryDirectory()
        self.addCleanup(self._repository.cleanup)
        self.repository_root = Path(self._repository.name)
        materialize_frozen_code_repository(
            self.repository_root,
            (ROOT / "specs/001-recallpack-v4/contracts/evaluation.schema.json").read_bytes(),
        )
        self.seed["code_hashes"] = compute_frozen_code_hashes(self.repository_root)

    def replace_public_artifact(
        self,
        seed: dict,
        artifacts: dict[str, bytes],
        slot: str,
        prefix: str,
        value: object,
        *,
        raw: bool = False,
    ) -> None:
        scenario = next(item for item in seed["scenario_plan"] if item["scenario_slot"] == slot)
        artifact_id = scenario[f"{prefix}_artifact_id"]
        payload = value if raw else canonical_bytes(value)
        artifacts[artifact_id] = payload
        record = seed["frozen_input_artifact_catalog"][artifact_id]
        record["sha256"] = sha256_bytes(payload)
        record["bytes"] = len(payload)
        scenario[f"{prefix}_sha256"] = sha256_bytes(payload)

    def test_b1_python_and_node_match_committed_golden_vectors(self) -> None:
        vectors = json.loads(VECTORS.read_text(encoding="utf-8"))
        for vector in vectors["vectors"]:
            with self.subTest(vector=vector["name"]):
                payload = canonicalize_review_json(vector["value"])
                self.assertEqual(vector["canonical"].encode(), payload)
                self.assertEqual(vector["sha256"], sha256_bytes(payload))
        result = subprocess.run(
            ["node", "tools/verify_review_json_vectors.mjs", str(VECTORS)],
            cwd=ROOT,
            check=False,
            text=True,
            capture_output=True,
        )
        self.assertEqual(0, result.returncode, result.stderr)

    def test_b3_code_hash_roots_are_fixed_and_symlinks_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "src/recallpack").mkdir(parents=True)
            (root / "src/recallpack/a.py").write_text("x = 1\n")
            (root / "evaluation/runner").mkdir(parents=True)
            (root / "evaluation/runner/run.py").write_text("print('ok')\n")
            (root / "evaluation/Dockerfile").write_text("FROM scratch\n")
            (root / "evaluation/.dockerignore").write_text(".git\n")
            schema = root / "specs/001-recallpack-v4/contracts/evaluation.schema.json"
            schema.parent.mkdir(parents=True)
            schema.write_bytes((ROOT / "specs/001-recallpack-v4/contracts/evaluation.schema.json").read_bytes())
            (root / "requirements-v4.txt").write_text("jsonschema==4.26.0\n")
            first = compute_frozen_code_hashes(root)
            (root / "unclassified.py").write_text("ignored = True\n")
            self.assertEqual(first, compute_frozen_code_hashes(root))
            os.symlink(root / "src/recallpack/a.py", root / "src/recallpack/link.py")
            with self.assertRaisesRegex(ValueError, "invalid_review_seed /code_hashes"):
                compute_frozen_code_hashes(root)

    def test_b3_code_hash_roots_reject_cache_directories_and_bytecode(self) -> None:
        for relative_path, is_directory in (
            ("src/recallpack/__pycache__", True),
            ("src/recallpack/a.pyc", False),
            ("evaluation/runner/__pycache__", True),
            ("evaluation/runner/run.pyc", False),
        ):
            with self.subTest(relative_path=relative_path):
                with tempfile.TemporaryDirectory() as directory:
                    root = Path(directory)
                    (root / "src/recallpack").mkdir(parents=True)
                    (root / "src/recallpack/a.py").write_text("x = 1\n")
                    (root / "evaluation/runner").mkdir(parents=True)
                    (root / "evaluation/runner/run.py").write_text("print('ok')\n")
                    (root / "evaluation/Dockerfile").write_text("FROM scratch\n")
                    (root / "evaluation/.dockerignore").write_text(".git\n")
                    schema = root / "specs/001-recallpack-v4/contracts/evaluation.schema.json"
                    schema.parent.mkdir(parents=True)
                    schema.write_bytes(
                        (ROOT / "specs/001-recallpack-v4/contracts/evaluation.schema.json").read_bytes()
                    )
                    (root / "requirements-v4.txt").write_text("jsonschema==4.26.0\n")
                    target = root / relative_path
                    if is_directory:
                        target.mkdir()
                    else:
                        target.write_bytes(b"bytecode")
                    with self.assertRaisesRegex(
                        ValueError,
                        "invalid_review_seed /code_hashes",
                    ):
                        compute_frozen_code_hashes(root)

    def test_b4_all_external_slot_mutations_reject_with_stable_code(self) -> None:
        mutations = []
        missing = copy.deepcopy(self.seed)
        missing["external_artifact_slots"].pop()
        mutations.append(missing)
        extra = copy.deepcopy(self.seed)
        extra["external_artifact_slots"].append(copy.deepcopy(extra["external_artifact_slots"][0]))
        mutations.append(extra)
        wrong = copy.deepcopy(self.seed)
        wrong["external_artifact_slots"][0]["kind"] = "fixture"
        mutations.append(wrong)
        crossed = copy.deepcopy(self.seed)
        crossed["external_artifact_slots"][0]["scenario_slot"] = "deepagents"
        mutations.append(crossed)
        for seed in mutations:
            with self.subTest(seed=seed["external_artifact_slots"]):
                with self.assertRaisesRegex(ValueError, "external_artifact_set_mismatch"):
                    validate_evaluation_review_seed(seed, artifact_bytes=self.artifacts)

    def test_b6_all_repeated_character_sentinels_are_rejected(self) -> None:
        seed_hash = review_json_sha256(self.seed)
        for character in "0123456789abcdef":
            attestation, receipt = build_attestation(self.seed, seed_hash)
            attestation["external_artifacts"][0]["content_sha256"] = character * 64
            with self.subTest(character=character):
                with self.assertRaisesRegex(ValueError, "invalid_review_attestation"):
                    validate_external_review_attestation(attestation, self.seed, receipt)

    def test_b16_provenance_contract_and_registry_binding_fail_closed(self) -> None:
        artifact_id = "provenance_projectodyssey"
        original = json.loads(self.artifacts[artifact_id])
        mutations = []
        for field in tuple(original):
            value = copy.deepcopy(original)
            value.pop(field)
            mutations.append(value)
        extra = copy.deepcopy(original)
        extra["extra"] = True
        mutations.append(extra)
        for field, value in (
            ("repository_url", "https://github.com/getzep/graphiti"),
            ("license_id", "Apache-2.0"),
            ("scenario_slot", "deepagents"),
            ("commit_refs", []),
            ("commit_refs", ["abc123"]),
            ("authored_summary_sha256", "9" * 64),
        ):
            mutation = copy.deepcopy(original)
            mutation[field] = value
            mutations.append(mutation)
        for index, value in enumerate(mutations):
            with self.subTest(index=index):
                seed = copy.deepcopy(self.seed)
                artifacts = dict(self.artifacts)
                self.replace_public_artifact(seed, artifacts, "projectodyssey", "provenance", value)
                with self.assertRaisesRegex(ValueError, "invalid_scenario_identity"):
                    validate_evaluation_review_seed(seed, artifact_bytes=artifacts)

    def test_public_fixture_and_repository_digests_bind_catalog_bytes(self) -> None:
        for field in ("fixture_sha256", "repository_snapshot_sha256"):
            with self.subTest(field=field):
                seed = copy.deepcopy(self.seed)
                scenario = next(
                    item
                    for item in seed["scenario_plan"]
                    if item["scenario_slot"] == "projectodyssey"
                )
                scenario[field] = "9" * 64
                with self.assertRaisesRegex(
                    ValueError,
                    "invalid_scenario_identity",
                ):
                    validate_evaluation_review_seed(
                        seed,
                        artifact_bytes=self.artifacts,
                    )

    def test_public_json_semantic_digest_must_equal_catalog_raw_digest(self) -> None:
        seed = copy.deepcopy(self.seed)
        artifacts = dict(self.artifacts)
        scenario = next(
            item
            for item in seed["scenario_plan"]
            if item["scenario_slot"] == "projectodyssey"
        )
        artifact_id = scenario["source_ledger_artifact_id"]
        value = json.loads(artifacts[artifact_id])
        noncanonical = json.dumps(value, indent=2).encode("utf-8")
        artifacts[artifact_id] = noncanonical
        record = seed["frozen_input_artifact_catalog"][artifact_id]
        record["sha256"] = sha256_bytes(noncanonical)
        record["bytes"] = len(noncanonical)
        with self.assertRaisesRegex(ValueError, "invalid_scenario_identity"):
            validate_evaluation_review_seed(seed, artifact_bytes=artifacts)

    def test_public_model_visible_event_timestamp_is_exact_gregorian_utc(self) -> None:
        seed = copy.deepcopy(self.seed)
        artifacts = dict(self.artifacts)
        scenario = next(
            item
            for item in seed["scenario_plan"]
            if item["scenario_slot"] == "projectodyssey"
        )
        ledger_id = scenario["source_ledger_artifact_id"]
        snapshot_id = scenario["model_visible_snapshot_artifact_id"]
        ledger = json.loads(artifacts[ledger_id])
        snapshot = json.loads(artifacts[snapshot_id])
        snapshot["events"][0]["observed_at"] = "1900-02-29T00:00:00Z"
        ledger["entries"][0]["event_sha256"] = sha256_bytes(
            canonical_bytes(snapshot["events"][0])
        )
        ledger_payload = canonical_bytes(ledger)
        ledger_sha = sha256_bytes(ledger_payload)
        snapshot["source_ledger_sha256"] = ledger_sha
        snapshot_payload = canonical_bytes(snapshot)
        artifacts[ledger_id] = ledger_payload
        artifacts[snapshot_id] = snapshot_payload
        for artifact_id, payload in (
            (ledger_id, ledger_payload),
            (snapshot_id, snapshot_payload),
        ):
            seed["frozen_input_artifact_catalog"][artifact_id]["sha256"] = sha256_bytes(
                payload
            )
            seed["frozen_input_artifact_catalog"][artifact_id]["bytes"] = len(payload)
        scenario["source_ledger_sha256"] = ledger_sha
        scenario["model_visible_snapshot_sha256"] = sha256_bytes(snapshot_payload)

        with self.assertRaisesRegex(ValueError, "invalid_scenario_identity"):
            validate_evaluation_review_seed(seed, artifact_bytes=artifacts)

    def test_b18_label_map_reference_and_attestation_digest_cannot_diverge(self) -> None:
        seed_hash = review_json_sha256(self.seed)
        attestation, receipt = build_attestation(self.seed, seed_hash)
        assembled = assemble_execution_manifest_41(
            self.seed,
            attestation,
            seed_receipt=receipt,
            artifact_bytes=self.artifacts,
            repository_root=self.repository_root,
        )
        assembled.manifest["label_hashes"]["projectodyssey"] = "9" * 64
        with self.assertRaisesRegex(ValueError, "review_seed_projection_mismatch"):
            validate_execution_manifest_41(
                assembled.manifest,
                artifact_bytes=assembled.artifact_bytes,
                repository_root=self.repository_root,
            )

    def test_b21_public_model_visible_snapshot_is_one_closed_envelope(self) -> None:
        artifact_id = "snapshot_projectodyssey"
        original = json.loads(self.artifacts[artifact_id])
        mutations: list[tuple[object, bool]] = [
            (b'{}\n{}\n', True),
            (original["events"], False),
            ({"record_type": "model_visible_snapshot", "events": original["events"]}, False),
            (b'{"record_type":"model_visible_snapshot","record_type":"x"}', True),
        ]
        reordered = copy.deepcopy(original)
        reordered["events"].reverse()
        mutations.append((reordered, False))
        duplicate = copy.deepcopy(original)
        duplicate["events"][1]["source_ref"] = duplicate["events"][0]["source_ref"]
        mutations.append((duplicate, False))
        missing = copy.deepcopy(original)
        missing["events"].pop()
        mutations.append((missing, False))
        false_summary = copy.deepcopy(original)
        false_summary["events"][0]["authored_summary"] = False
        mutations.append((false_summary, False))
        wrong_hash = copy.deepcopy(original)
        wrong_hash["events"][0]["summary"] = "mutated"
        mutations.append((wrong_hash, False))
        for index, (value, raw) in enumerate(mutations):
            with self.subTest(index=index):
                seed = copy.deepcopy(self.seed)
                artifacts = dict(self.artifacts)
                self.replace_public_artifact(
                    seed,
                    artifacts,
                    "projectodyssey",
                    "model_visible_snapshot",
                    value,
                    raw=raw,
                )
                with self.assertRaisesRegex(ValueError, "invalid_scenario_identity"):
                    validate_evaluation_review_seed(seed, artifact_bytes=artifacts)

    def test_b11_full_simulation_marker_is_required_but_not_public_evidence(self) -> None:
        seed, artifacts = build_full_seed()
        packet = {
            "simulation_marker": "simulated_external_reviewer_contract_test_only",
            "seed": seed,
            "artifact_bytes": artifacts,
        }
        self.assertEqual(
            "simulated_external_reviewer_contract_test_only",
            packet["simulation_marker"],
        )
        self.assertNotIn(
            b"simulated_external_reviewer_contract_test_only",
            canonicalize_review_json(seed),
        )
        packet.pop("simulation_marker")
        with self.assertRaisesRegex(ValueError, "missing simulation marker"):
            if packet.get("simulation_marker") != "simulated_external_reviewer_contract_test_only":
                raise ValueError("missing simulation marker")


if __name__ == "__main__":
    unittest.main()
