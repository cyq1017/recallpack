import copy
import hashlib
import importlib
import importlib.util
import json
import os
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from recallpack.budget import canonical_json


class Utf8Tokenizer:
    def count(self, text):
        return len(text.encode("utf-8"))


class BrokenTokenizer:
    def count(self, text):
        raise RuntimeError("tokenizer unavailable")


def sha256_bytes(payload):
    return hashlib.sha256(payload).hexdigest()


def render_pack_markdown(pack):
    lines = ["# RecallPack", ""]
    for memory in pack["memories"]:
        lines.extend(
            [
                f"## {memory['subject']}",
                "",
                memory["text"],
                "",
                f"- ID: `{memory['id']}`",
                f"- Type: `{memory['type']}`",
                f"- Scope: `{memory['scope']}`",
                f"- Source: `{memory['source_ref']}`",
                "- Lifecycle: `active`",
                "- Inclusion: `reranked_and_within_budget`",
                "",
            ]
        )
    return "\n".join(lines).rstrip() + "\n"


def runtime_steps():
    names = [
        ("validate_request", True, "succeeded"),
        ("load_active_snapshot", True, "succeeded"),
        ("embedding_top_20", False, "succeeded"),
        ("rerank", False, "succeeded"),
        ("budget_select", True, "succeeded"),
        ("render_artifacts", True, "succeeded"),
        ("publish_artifacts", True, "succeeded"),
    ]
    return [
        {
            "index": index,
            "name": name,
            "status": status,
            "duration_ms": index + 1,
            "deterministic": deterministic,
        }
        for index, (name, deterministic, status) in enumerate(names)
    ]


def provider_trace(role, input_tokens, output_tokens):
    return {
        "role": role,
        "provider_family": "deterministic_fake",
        "model_name": "text-embedding-v4" if role == "embedding" else "qwen3-rerank",
        "request_purpose": (
            "candidate_memory_retrieval_query"
            if role == "embedding"
            else "precision_rerank_active_memory_candidates"
        ),
        "input_item_count": 1,
        "input_token_estimate": input_tokens,
        "output_item_count": 1,
        "live": False,
        "deterministic_fallback": True,
        "request_id_present": True,
        "token_usage": {
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "total_tokens": input_tokens + output_tokens,
            "reported_by_provider": True,
        },
    }


def valid_bundle():
    pack = {
        "memories": [
            {
                "id": "mem_current",
                "type": "decision",
                "subject": "retry_policy",
                "text": "Use five attempts with exponential backoff.",
                "scope": "component:retry",
                "source_ref": "session-b:turn-001",
            }
        ]
    }
    trace = {
        "compile_id": "cmp_abc123",
        "request": {
            "project_id": "fresh-project",
            "goal": "Update retry behavior",
            "component": "retry",
            "budget_tokens": 512,
        },
        "memory_snapshot_seq": 3,
        "candidate_scores": [
            {
                "memory_id": "mem_current",
                "candidate_index": 0,
                "embedding_cosine": 0.9,
                "rerank_score": 0.8,
                "source_project_event_seq": 3,
                "lifecycle_status": "active",
                "scope": "component:retry",
                "source_ref": "session-b:turn-001",
            }
        ],
        "reranked_memory_ids": ["mem_current"],
        "selected_memory_ids": ["mem_current"],
        "omissions": [],
        "exact_token_count": 0,
        "tokenizer": {
            "encoding": "o200k_base",
            "package": "tiktoken",
            "package_version": "0.13.0",
            "exact": True,
        },
        "provider_traces": [
            provider_trace("embedding", 4, 0),
            provider_trace("rerank", 7, 2),
        ],
        "runtime_steps": runtime_steps(),
        "input_artifact_hashes": {
            "recallpack.json": "0" * 64,
            "PACK.md": "0" * 64,
        },
    }
    bundle = {
        "schema_version": "4.0",
        "semantic_rules_version": "compile-semantic-rules/4.0",
        "compile_id": "cmp_abc123",
        "pack": pack,
        "pack_markdown": render_pack_markdown(pack),
        "trace": trace,
        "files": [],
    }
    return finalize_bundle(bundle)


def valid_empty_bundle():
    bundle = valid_bundle()
    bundle["pack"] = {"memories": []}
    bundle["trace"].update(
        {
            "memory_snapshot_seq": 0,
            "candidate_scores": [],
            "reranked_memory_ids": [],
            "selected_memory_ids": [],
            "omissions": [],
            "provider_traces": [],
        }
    )
    bundle["trace"]["runtime_steps"][2]["status"] = "skipped"
    bundle["trace"]["runtime_steps"][3]["status"] = "skipped"
    return finalize_bundle(bundle)


def finalize_bundle(bundle):
    bundle["pack_markdown"] = render_pack_markdown(bundle["pack"])
    pack_bytes = canonical_json(bundle["pack"]).encode("utf-8")
    markdown_bytes = bundle["pack_markdown"].encode("utf-8")
    bundle["trace"]["exact_token_count"] = len(pack_bytes)
    bundle["trace"]["input_artifact_hashes"] = {
        "recallpack.json": sha256_bytes(pack_bytes),
        "PACK.md": sha256_bytes(markdown_bytes),
    }
    trace_bytes = canonical_json(bundle["trace"]).encode("utf-8")
    bundle["files"] = [
        {"name": "recallpack.json", "sha256": sha256_bytes(pack_bytes), "bytes": len(pack_bytes)},
        {"name": "PACK.md", "sha256": sha256_bytes(markdown_bytes), "bytes": len(markdown_bytes)},
        {"name": "trace.json", "sha256": sha256_bytes(trace_bytes), "bytes": len(trace_bytes)},
    ]
    return bundle


class CompileArtifactV4Tests(unittest.TestCase):
    def artifacts_module(self):
        spec = importlib.util.find_spec("recallpack.artifacts")
        self.assertIsNotNone(
            spec,
            "T020 requires recallpack.artifacts without causing a collection-time import error",
        )
        return importlib.import_module("recallpack.artifacts")

    def validator(self):
        validator = getattr(self.artifacts_module(), "validate_compile_bundle_v4", None)
        self.assertTrue(callable(validator), "T020 requires validate_compile_bundle_v4")
        return validator

    def publisher(self):
        publisher = getattr(self.artifacts_module(), "publish_compile_bundle_v4", None)
        self.assertTrue(callable(publisher), "T020 requires publish_compile_bundle_v4")
        return publisher

    def assert_invalid(self, bundle, code):
        with self.assertRaisesRegex(ValueError, code):
            self.validator()(bundle, tokenizer=Utf8Tokenizer())

    def test_valid_closed_bundle_cross_references_and_arithmetic_are_accepted(self):
        self.validator()(valid_bundle(), tokenizer=Utf8Tokenizer())

    def test_valid_zero_candidate_bundle_skips_both_model_steps_and_still_validates(self):
        self.validator()(valid_empty_bundle(), tokenizer=Utf8Tokenizer())

    def test_pack_and_trace_memory_cross_reference_mismatch_is_rejected(self):
        bundle = valid_bundle()
        bundle["trace"]["selected_memory_ids"] = ["mem_other"]
        finalize_bundle(bundle)

        self.assert_invalid(bundle, "invalid_compile_reference")

    def test_provider_token_arithmetic_mismatch_is_rejected(self):
        bundle = valid_bundle()
        bundle["trace"]["provider_traces"][1]["token_usage"]["total_tokens"] = 99
        finalize_bundle(bundle)

        self.assert_invalid(bundle, "invalid_compile_usage")

    def test_non_finite_embedding_or_rerank_scores_are_rejected(self):
        for field in ("embedding_cosine", "rerank_score"):
            with self.subTest(field=field):
                bundle = valid_bundle()
                bundle["trace"]["candidate_scores"][0][field] = float("nan")
                finalize_bundle(bundle)

                self.assert_invalid(bundle, "invalid_compile_order")

    def test_private_paths_and_secret_shaped_content_are_rejected(self):
        invalid_values = [
            (
                "Read /" + "Users/alice/private/recallpack.sqlite3",
                "private_path_detected",
            ),
            (
                "Use token " + "sk-" + "abcdefghijklmnopqrstuvwxyz123456",
                "secret_material_detected",
            ),
            (
                "Use token " + "sk-" + "abc_def-12345678901234567890",
                "secret_material_detected",
            ),
        ]
        for text, code in invalid_values:
            with self.subTest(code=code):
                bundle = valid_bundle()
                bundle["pack"]["memories"][0]["text"] = text
                finalize_bundle(bundle)
                self.assert_invalid(bundle, code)

    def test_model_steps_may_be_skipped_only_together_for_zero_candidates(self):
        invalid_bundles = []

        nonempty_embedding_skipped = valid_bundle()
        nonempty_embedding_skipped["trace"]["runtime_steps"][2]["status"] = "skipped"
        invalid_bundles.append(nonempty_embedding_skipped)

        nonempty_rerank_skipped = valid_bundle()
        nonempty_rerank_skipped["trace"]["runtime_steps"][3]["status"] = "skipped"
        invalid_bundles.append(nonempty_rerank_skipped)

        empty_embedding_executed = valid_empty_bundle()
        empty_embedding_executed["trace"]["runtime_steps"][2]["status"] = "succeeded"
        invalid_bundles.append(empty_embedding_executed)

        empty_with_provider_trace = valid_empty_bundle()
        empty_with_provider_trace["trace"]["provider_traces"] = [
            provider_trace("embedding", 0, 0)
        ]
        invalid_bundles.append(empty_with_provider_trace)

        deterministic_step_skipped = valid_bundle()
        deterministic_step_skipped["trace"]["runtime_steps"][4]["status"] = "skipped"
        invalid_bundles.append(deterministic_step_skipped)

        for bundle in invalid_bundles:
            finalize_bundle(bundle)
            self.assert_invalid(bundle, "invalid_runtime_steps")

    def test_tokenizer_failure_is_a_stable_validation_error(self):
        with self.assertRaisesRegex(ValueError, "invalid_compile_usage"):
            self.validator()(valid_bundle(), tokenizer=BrokenTokenizer())

        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(ValueError, "artifact_validation_failed"):
                self.publisher()(
                    valid_bundle(),
                    artifact_root=Path(tmp),
                    tokenizer=BrokenTokenizer(),
                )

        with patch(
            "recallpack.artifacts.default_tokenizer",
            side_effect=RuntimeError("tokenizer dependency missing"),
        ):
            with self.assertRaisesRegex(ValueError, "invalid_compile_usage"):
                self.validator()(valid_bundle())

    def test_literal_filenames_and_closed_trace_forbid_aliases_or_self_hash(self):
        wrong_filename = valid_bundle()
        wrong_filename["files"][0]["name"] = "pack.json"
        self.assert_invalid(wrong_filename, "artifact")

        self_referential = valid_bundle()
        self_referential["trace"]["trace_sha256"] = "a" * 64
        finalize_bundle(self_referential)
        self.assert_invalid(self_referential, "artifact")

    def test_publication_returns_literal_complete_files_without_temp_visibility(self):
        bundle = valid_bundle()
        with tempfile.TemporaryDirectory() as tmp:
            with patch("os.fsync", wraps=os.fsync) as fsync:
                result = self.publisher()(
                    bundle,
                    artifact_root=Path(tmp),
                    tokenizer=Utf8Tokenizer(),
                )
            final = Path(tmp) / "compiles" / "cmp_abc123"

            self.assertEqual(sorted(path.name for path in final.iterdir()), [
                "PACK.md",
                "recallpack.json",
                "trace.json",
            ])
            expected_files = {
                "recallpack.json": canonical_json(bundle["pack"]).encode("utf-8"),
                "PACK.md": bundle["pack_markdown"].encode("utf-8"),
                "trace.json": canonical_json(bundle["trace"]).encode("utf-8"),
            }
            for name, expected_bytes in expected_files.items():
                with self.subTest(name=name):
                    actual_bytes = (final / name).read_bytes()
                    self.assertEqual(actual_bytes, expected_bytes)
                    self.assertEqual(
                        next(item["sha256"] for item in result["files"] if item["name"] == name),
                        sha256_bytes(actual_bytes),
                    )
            self.assertEqual([item["name"] for item in result["files"]], [
                "recallpack.json",
                "PACK.md",
                "trace.json",
            ])
            self.assertEqual(list((Path(tmp) / "compiles").glob(".*")), [])
            self.assertNotIn(str(Path(tmp).resolve()), str(result))
            self.assertGreaterEqual(fsync.call_count, 4, "three files and the published directory must be fsynced")

    def test_concurrent_same_compile_id_has_one_winner_without_overwrite(self):
        module = self.artifacts_module()
        publisher = self.publisher()
        barrier = threading.Barrier(3)
        results = []
        errors = []

        def publish(bundle, root):
            barrier.wait(timeout=5)
            try:
                results.append(
                    publisher(bundle, artifact_root=root, tokenizer=Utf8Tokenizer())
                )
            except ValueError as exc:
                errors.append(str(exc))

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            threads = [
                threading.Thread(target=publish, args=(copy.deepcopy(valid_bundle()), root))
                for _ in range(2)
            ]
            for thread in threads:
                thread.start()
            barrier.wait(timeout=5)
            for thread in threads:
                thread.join(timeout=5)

            self.assertTrue(all(not thread.is_alive() for thread in threads))
            self.assertEqual(len(results), 1)
            self.assertEqual(len(errors), 1)
            self.assertIn("artifact_publication_failed", errors[0])
            final = root / "compiles" / "cmp_abc123"
            self.assertEqual(sorted(path.name for path in final.iterdir()), [
                "PACK.md",
                "recallpack.json",
                "trace.json",
            ])
            published = copy.deepcopy(valid_bundle())
            published["pack"] = json.loads(
                (final / "recallpack.json").read_text(encoding="utf-8")
            )
            published["pack_markdown"] = (final / "PACK.md").read_text(encoding="utf-8")
            published["trace"] = json.loads(
                (final / "trace.json").read_text(encoding="utf-8")
            )
            module.validate_compile_bundle_v4(published, tokenizer=Utf8Tokenizer())

    def test_existing_compile_directory_collision_never_overwrites(self):
        bundle = valid_bundle()
        with tempfile.TemporaryDirectory() as tmp:
            final = Path(tmp) / "compiles" / "cmp_abc123"
            final.mkdir(parents=True)
            sentinel = final / "owner.txt"
            sentinel.write_text("first publication", encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "artifact_publication_failed"):
                self.publisher()(
                    bundle,
                    artifact_root=Path(tmp),
                    tokenizer=Utf8Tokenizer(),
                )

            self.assertEqual(sentinel.read_text(encoding="utf-8"), "first publication")
            self.assertEqual(sorted(path.name for path in final.iterdir()), ["owner.txt"])

    def test_validation_failure_publishes_no_final_or_partial_directory(self):
        bundle = valid_bundle()
        bundle["trace"]["selected_memory_ids"] = ["mem_unknown"]
        finalize_bundle(bundle)
        with tempfile.TemporaryDirectory() as tmp:
            compiles = Path(tmp) / "compiles"
            foreign = compiles / ".foreign-writer.tmp"
            foreign.mkdir(parents=True)
            sentinel = foreign / "owner.txt"
            sentinel.write_text("not owned by this publication", encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "artifact_validation_failed"):
                self.publisher()(
                    bundle,
                    artifact_root=Path(tmp),
                    tokenizer=Utf8Tokenizer(),
                )

            self.assertFalse((compiles / "cmp_abc123").exists())
            self.assertEqual(sentinel.read_text(encoding="utf-8"), "not owned by this publication")
            self.assertEqual(sorted(path.name for path in compiles.iterdir()), [foreign.name])


if __name__ == "__main__":
    unittest.main()
