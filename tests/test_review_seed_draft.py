from __future__ import annotations

import hashlib
from pathlib import Path
import tempfile
import unittest

from recallpack.evidence import (
    canonicalize_review_json,
    parse_review_json,
    validate_evaluation_review_seed,
)
from recallpack.review_seed_draft import (
    build_deterministic_file_bundle,
    build_r2_review_seed_draft,
    compute_evaluator_build_context_sha256,
)


ROOT = Path(__file__).resolve().parents[1]
IMAGE_DIGEST = "sha256:8d985a3c452ed2640b1ab9d3cc8b7de0d35be1453f9f6d0c3890fdc32b61fe54"


class ReviewSeedDraftTests(unittest.TestCase):
    def setUp(self) -> None:
        self._temporary = tempfile.TemporaryDirectory(
            prefix=".review-seed-draft-test-",
            dir=ROOT,
        )
        self.addCleanup(self._temporary.cleanup)
        self.output_relative = (
            Path(self._temporary.name).relative_to(ROOT) / "review-seed"
        ).as_posix()

    def _build(self):
        return build_r2_review_seed_draft(
            repository_root=ROOT,
            output_dir=self.output_relative,
            created_at="2026-07-18T00:00:00Z",
            evaluator_image_digest=IMAGE_DIGEST,
            platform="linux/arm64",
        )

    def test_builds_real_r2_draft_from_source_backed_inputs(self) -> None:
        result = self._build()
        seed_bytes = result.seed_draft_path.read_bytes()
        seed = parse_review_json(seed_bytes)
        self.assertEqual(seed_bytes, canonicalize_review_json(seed))
        self.assertEqual("R2", seed["target_rung"])
        self.assertEqual(
            ["projectodyssey", "deepagents"],
            [item["scenario_slot"] for item in seed["scenario_plan"]],
        )
        self.assertEqual(30, len(seed["execution_order"]))
        self.assertEqual(list(range(30)), [item["slot_index"] for item in seed["execution_order"]])
        self.assertEqual(
            ["structural_runtime"],
            [item["claim_type"] for item in seed["claim_declarations"]],
        )
        self.assertEqual(
            ["pyproject.toml", "src/ci_policy.py", "src/package_policy.py"],
            seed["comparison_contract"]["writable_paths"],
        )
        self.assertEqual("live", seed["provider_settings"]["mode"])
        self.assertFalse(seed["provider_settings"]["deterministic_fallback"])
        self.assertEqual(6, len(seed["external_artifact_slots"]))
        self.assertEqual(18, len(seed["frozen_input_artifact_catalog"]))

        catalog = seed["frozen_input_artifact_catalog"]
        artifacts = {
            artifact_id: (ROOT / record["relative_path"]).read_bytes()
            for artifact_id, record in catalog.items()
        }
        validate_evaluation_review_seed(seed, artifact_bytes=artifacts)
        self.assertFalse(
            {"relation_label_ledger", "leakage_review"}
            & {record["kind"] for record in catalog.values()}
        )

        for slot, expected_paths in (
            ("projectodyssey", ["README.md", "pyproject.toml", "src/ci_policy.py"]),
            ("deepagents", ["pyproject.toml", "src/package_policy.py"]),
        ):
            repository = parse_review_json(artifacts[f"repository_snapshot_{slot}"])
            self.assertEqual(expected_paths, [item["path"] for item in repository["files"]])
            self.assertFalse(any("__pycache__" in item["path"] for item in repository["files"]))

            hidden_bundle = build_deterministic_file_bundle(
                ROOT / "evaluation/hidden-tests" / slot,
                scenario_slot=slot,
                purpose="hidden_tests",
            )
            expected_hidden_hash = hashlib.sha256(
                canonicalize_review_json(hidden_bundle)
            ).hexdigest()
            self.assertEqual(
                expected_hidden_hash.encode("ascii"),
                artifacts[f"hidden_test_hash_{slot}"],
            )

        build_record = parse_review_json(artifacts["evaluator_image_build_record"])
        self.assertEqual(IMAGE_DIGEST, build_record["output_image_digest"])
        self.assertEqual(
            compute_evaluator_build_context_sha256(ROOT / "evaluation"),
            build_record["build_context_sha256"],
        )

    def test_refuses_to_replace_an_existing_draft_directory(self) -> None:
        self._build()
        with self.assertRaises(FileExistsError):
            self._build()


if __name__ == "__main__":
    unittest.main()
