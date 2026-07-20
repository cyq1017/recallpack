from __future__ import annotations

import copy
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from recallpack.evidence import (
    canonicalize_review_json,
    compute_frozen_code_hashes,
    derive_external_artifact_slots,
    parse_review_json,
    review_json_sha256,
    validate_evaluation_review_seed,
)
from tests._v41_review_seed_fixtures import (
    build_r2_seed,
    materialize_frozen_code_repository,
)


ROOT = Path(__file__).resolve().parents[1]
SCHEMA_PATH = ROOT / "specs/001-recallpack-v4/contracts/evaluation.schema.json"
RUNBOOK_PATH = ROOT / "specs/001-recallpack-v4/review-seed-operator-runbook.md"


class ReviewSeedGenerationTests(unittest.TestCase):
    def setUp(self) -> None:
        self._temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self._temporary.cleanup)
        self.repository_root = Path(self._temporary.name).resolve()
        materialize_frozen_code_repository(
            self.repository_root,
            SCHEMA_PATH.read_bytes(),
        )
        self.seed, self.artifact_bytes = build_r2_seed()
        self.seed["code_hashes"] = {key: "0" * 64 for key in self.seed["code_hashes"]}
        self.seed["external_artifact_slots"] = []
        for artifact_id, record in self.seed["frozen_input_artifact_catalog"].items():
            record["relative_path"] = f"frozen-inputs/{artifact_id}.bin"
            path = self.repository_root / record["relative_path"]
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(self.artifact_bytes[artifact_id])
        self.operator_root = self.repository_root / "operator"
        self.operator_root.mkdir()
        self.draft_relative = "operator/seed-draft.json"
        self.output_relative = "operator/review-seed-export"
        self._write_draft(self.seed)

    def _write_draft(self, seed: dict) -> None:
        (self.repository_root / self.draft_relative).write_bytes(
            canonicalize_review_json(seed)
        )

    def _generate(self, *, output_relative: str | None = None):
        from recallpack.review_seed_generation import generate_review_seed_package

        return generate_review_seed_package(
            repository_root=self.repository_root,
            seed_draft=self.draft_relative,
            output_dir=output_relative or self.output_relative,
        )

    def test_evaluator_docker_context_excludes_private_evidence(self) -> None:
        patterns = {
            line.strip()
            for line in (ROOT / "evaluation/.dockerignore").read_text().splitlines()
            if line.strip() and not line.lstrip().startswith("#")
        }
        self.assertTrue({"scenarios", "evidence"}.issubset(patterns))

    def test_generation_derives_authority_and_writes_exact_canonical_package(self) -> None:
        result = self._generate()
        output = self.repository_root / self.output_relative

        self.assertEqual(
            {
                "evaluation-review-seed.json",
                "evaluation-review-seed.sha256",
                "external-artifact-slots.json",
                "review-seed-generation-report.json",
            },
            {path.name for path in output.iterdir()},
        )
        seed_bytes = (output / "evaluation-review-seed.json").read_bytes()
        generated_seed = parse_review_json(seed_bytes)
        self.assertEqual(seed_bytes, canonicalize_review_json(generated_seed))
        self.assertEqual(
            compute_frozen_code_hashes(self.repository_root),
            generated_seed["code_hashes"],
        )
        self.assertEqual(
            derive_external_artifact_slots(generated_seed),
            generated_seed["external_artifact_slots"],
        )
        validate_evaluation_review_seed(
            generated_seed,
            artifact_bytes=self.artifact_bytes,
            repository_root=self.repository_root,
        )
        seed_hash = review_json_sha256(generated_seed)
        self.assertEqual(
            f"{seed_hash}\n".encode("ascii"),
            (output / "evaluation-review-seed.sha256").read_bytes(),
        )
        slots_bytes = (output / "external-artifact-slots.json").read_bytes()
        self.assertEqual(
            canonicalize_review_json(generated_seed["external_artifact_slots"]),
            slots_bytes,
        )
        report_bytes = (output / "review-seed-generation-report.json").read_bytes()
        report = parse_review_json(report_bytes)
        self.assertEqual(report_bytes, canonicalize_review_json(report))
        self.assertEqual(
            {
                "authorizes_execution": False,
                "contains_external_content": False,
                "credentials_read": False,
                "evaluation_review_seed_bytes": len(seed_bytes),
                "evaluation_review_seed_file": "evaluation-review-seed.json",
                "evaluation_review_seed_sha256": seed_hash,
                "evaluation_review_seed_sha256_file": "evaluation-review-seed.sha256",
                "external_artifact_slot_count": len(
                    generated_seed["external_artifact_slots"]
                ),
                "external_artifact_slots_bytes": len(slots_bytes),
                "external_artifact_slots_file": "external-artifact-slots.json",
                "external_artifact_slots_sha256": review_json_sha256(
                    generated_seed["external_artifact_slots"]
                ),
                "network_calls_made": False,
                "next_gate": "external_review_and_attestation",
                "record_type": "review_seed_generation_report",
                "report_version": "review-seed-generation/4.1",
            },
            report,
        )
        self.assertEqual(seed_hash, result.review_seed_sha256)
        self.assertEqual(len(generated_seed["external_artifact_slots"]), result.slot_count)
        for payload in (seed_bytes, slots_bytes, report_bytes):
            self.assertNotIn(str(self.repository_root).encode(), payload)

    def test_existing_target_and_failed_validation_publish_nothing(self) -> None:
        existing = self.repository_root / self.output_relative
        existing.mkdir()
        marker = existing / "keep.txt"
        marker.write_text("keep", encoding="utf-8")
        with self.assertRaisesRegex(FileExistsError, "output target already exists"):
            self._generate()
        self.assertEqual("keep", marker.read_text(encoding="utf-8"))

        invalid = copy.deepcopy(self.seed)
        invalid["frozen_input_artifact_catalog"]["patch_contract"]["bytes"] += 1
        self._write_draft(invalid)
        failed_output = "operator/failed-export"
        with self.assertRaisesRegex(ValueError, "invalid_artifact_reference"):
            self._generate(output_relative=failed_output)
        self.assertFalse((self.repository_root / failed_output).exists())
        self.assertEqual([], list(self.operator_root.glob(".failed-export.tmp-*")))

    def test_draft_and_catalog_paths_reject_unsafe_or_aliased_inputs(self) -> None:
        from recallpack.review_seed_generation import generate_review_seed_package

        with self.assertRaisesRegex(ValueError, "invalid_seed_generation_path"):
            generate_review_seed_package(
                repository_root=self.repository_root,
                seed_draft="../seed.json",
                output_dir=self.output_relative,
            )

        alias_root = self.repository_root.parent / "review-seed-root-alias"
        alias_root.symlink_to(self.repository_root, target_is_directory=True)
        self.addCleanup(alias_root.unlink)
        with self.assertRaisesRegex(ValueError, "canonical and non-symlinked"):
            generate_review_seed_package(
                repository_root=alias_root,
                seed_draft=self.draft_relative,
                output_dir="operator/noncanonical-root-export",
            )

        original_draft = self.repository_root / self.draft_relative
        hardlinked_draft = self.operator_root / "hardlinked-draft.json"
        os.link(original_draft, hardlinked_draft)
        with self.assertRaisesRegex(ValueError, "hardlinked input"):
            generate_review_seed_package(
                repository_root=self.repository_root,
                seed_draft="operator/hardlinked-draft.json",
                output_dir=self.output_relative,
            )

        symlinked_draft = self.operator_root / "symlinked-draft.json"
        symlinked_draft.symlink_to(original_draft)
        with self.assertRaisesRegex(ValueError, "symlink|not permitted"):
            generate_review_seed_package(
                repository_root=self.repository_root,
                seed_draft="operator/symlinked-draft.json",
                output_dir=self.output_relative,
            )

        unsafe = copy.deepcopy(self.seed)
        unsafe["frozen_input_artifact_catalog"]["patch_contract"][
            "relative_path"
        ] = "frozen-inputs//patch_contract.bin"
        self._write_draft(unsafe)
        with self.assertRaisesRegex(ValueError, "invalid_seed_generation_path"):
            self._generate()

    def test_code_hashes_reject_hardlinks_and_symlinked_directories(self) -> None:
        runtime = self.repository_root / "src/recallpack/runtime.py"
        os.link(runtime, self.repository_root / "src/recallpack/duplicate.py")
        with self.assertRaisesRegex(ValueError, "hardlinked input"):
            compute_frozen_code_hashes(self.repository_root)

        (self.repository_root / "src/recallpack/duplicate.py").unlink()
        real_dir = self.repository_root / "src/recallpack/nested-real"
        real_dir.mkdir()
        (real_dir / "nested.py").write_text("VALUE = 1\n", encoding="utf-8")
        (self.repository_root / "src/recallpack/nested-link").symlink_to(
            real_dir,
            target_is_directory=True,
        )
        with self.assertRaisesRegex(ValueError, "symlinked directory"):
            compute_frozen_code_hashes(self.repository_root)

    def test_cli_is_credential_free_and_stdout_is_sanitized(self) -> None:
        env = dict(os.environ)
        env["PYTHONPATH"] = str(ROOT / "src")
        env["DASHSCOPE_API_KEY"] = "must-not-be-read"
        completed = subprocess.run(
            [
                sys.executable,
                str(ROOT / "tools/generate_review_seed.py"),
                "--repository-root",
                str(self.repository_root),
                "--seed-draft",
                self.draft_relative,
                "--output-dir",
                "operator/cli-export",
            ],
            cwd=ROOT,
            env=env,
            check=True,
            capture_output=True,
            text=True,
        )
        self.assertIn("status=review_seed_generated", completed.stdout)
        self.assertIn("credentials_read=false", completed.stdout)
        self.assertIn("network_calls_made=false", completed.stdout)
        self.assertIn("authorizes_execution=false", completed.stdout)
        self.assertNotIn(str(self.repository_root), completed.stdout)
        self.assertNotIn("must-not-be-read", completed.stdout)

        (self.repository_root / self.draft_relative).write_bytes(
            b'{"DASHSCOPE_API_KEY":1,"DASHSCOPE_API_KEY":2,'
            b'"/private/operator/person":3}'
        )
        failed = subprocess.run(
            [
                sys.executable,
                str(ROOT / "tools/generate_review_seed.py"),
                "--repository-root",
                str(self.repository_root),
                "--seed-draft",
                self.draft_relative,
                "--output-dir",
                "operator/failed-cli-export",
            ],
            cwd=ROOT,
            env=env,
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(1, failed.returncode)
        self.assertEqual(
            "status=review_seed_generation_failed error=invalid_review_seed\n",
            failed.stderr,
        )
        self.assertNotIn("DASHSCOPE_API_KEY", failed.stderr)
        self.assertNotIn("must-not-be-read", failed.stderr)
        self.assertNotIn("/private/operator/person", failed.stderr)
        self.assertNotIn(str(self.repository_root), failed.stderr)

    def test_operator_runbook_freezes_t052_t054_custody_order(self) -> None:
        runbook = RUNBOOK_PATH.read_text(encoding="utf-8")
        for required in (
            "tools/generate_review_seed.py",
            "T069 does not generate the production T052 seed",
            "outside the RecallPack workspace",
            "before authoring any external artifact",
            "Do not copy sealed external content into the workspace",
            "Import only the cycle-v3 sanitized attestation source",
            "evaluation/evidence/review-seed-cycles/cycle-v3/protocol/external-review-attestation.json",
            "hash-reference records are derived locally",
            "No provider or sandbox action may begin",
        ):
            self.assertIn(required, runbook)

    def test_public_bundle_contains_command_and_contract_not_operator_custody_files(self) -> None:
        from recallpack.submission_bundle import build_submission_bundle

        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary) / "sanitized-source"
            build_submission_bundle(ROOT, source)
            evidence_root = source / "evaluation" / "evidence"
            planted = (
                evidence_root
                / "review-seed"
                / "export"
                / "evaluation-review-seed.json"
            )
            planted.parent.mkdir(parents=True)
            planted.write_text("seed must remain private", encoding="utf-8")
            protocol = evidence_root / "protocol"
            protocol.mkdir()
            (protocol / "external-review-attestation.json").write_text(
                "attestation must remain private",
                encoding="utf-8",
            )
            sealed = evidence_root / "sealed" / "required-memory-labels.json"
            sealed.parent.mkdir()
            sealed.write_text("sealed labels must remain private", encoding="utf-8")
            misplaced = source / "evaluation" / "attestation-import"
            misplaced.mkdir()
            for filename in (
                "external-review-attestation.json",
                "seed-receipt.json",
                "required-memory-labels.json",
            ):
                (misplaced / filename).write_text(
                    "misplaced custody material must remain private",
                    encoding="utf-8",
                )

            target = Path(temporary) / "recallpack-submission"
            result = build_submission_bundle(source, target)
            self.assertIn("tools/generate_review_seed.py", result.files)
            self.assertIn(
                "specs/001-recallpack-v4/contracts/review-seed-generation-command.md",
                result.files,
            )
            self.assertIn(
                "specs/001-recallpack-v4/review-seed-operator-runbook.md",
                result.files,
            )
            self.assertFalse(
                any("external-review-attestation.json" in path for path in result.files)
            )
            self.assertFalse(any("seed-receipt.json" in path for path in result.files))
            self.assertFalse(any(path.startswith("evaluation/evidence/") for path in result.files))
            self.assertFalse(any(path.startswith("evaluation/attestation-import/") for path in result.files))

            linked = source / "evaluation" / "runner" / "linked-attestation.json"
            linked.symlink_to(planted)
            with self.assertRaisesRegex(ValueError, "symlink"):
                build_submission_bundle(
                    source,
                    Path(temporary) / "symlinked-source-bundle",
                )
            linked.unlink()

            hardlinked = (
                source / "evaluation" / "runner" / "hardlinked-attestation.json"
            )
            os.link(planted, hardlinked)
            with self.assertRaisesRegex(ValueError, "hardlink"):
                build_submission_bundle(
                    source,
                    Path(temporary) / "hardlinked-source-bundle",
                )


if __name__ == "__main__":
    unittest.main()
