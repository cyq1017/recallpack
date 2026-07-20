import json
import os
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from recallpack import submission_bundle
from recallpack.submission_bundle import build_submission_bundle, scan_submission_bundle
from tools import fresh_clone_smoke
from tools.fresh_clone_smoke import (
    _assert_public_surface,
    _assert_runtime_dependencies,
    _fresh_env,
    _ignore_runtime_artifacts,
)


ROOT = Path(__file__).resolve().parents[1]


class SubmissionBundleTests(unittest.TestCase):
    def test_external_review_zip_packages_sanitized_bundle_with_prompt(self):
        from tools.build_external_review_zip import build_external_review_zip

        with tempfile.TemporaryDirectory() as tmp:
            bundle = Path(tmp) / "recallpack-submission"
            archive = Path(tmp) / "recallpack-external-review.zip"
            build_submission_bundle(ROOT, bundle)

            payload = build_external_review_zip(bundle, archive)

            self.assertTrue(archive.is_file())
            self.assertEqual(archive.resolve(), payload["archive"])
            self.assertEqual("ready_for_external_review_upload", payload["status"])
            self.assertFalse(payload["requires_credentials"])
            self.assertFalse(payload["network_calls_made"])
            self.assertTrue(payload["source_scan_clean"])
            with zipfile.ZipFile(archive) as zip_file:
                names = set(zip_file.namelist())
                self.assertIn("EXTERNAL_REVIEW_PROMPT.md", names)
                self.assertIn("EXTERNAL_REVIEW_MANIFEST.json", names)
                self.assertIn("recallpack-submission/README.md", names)
                self.assertIn("recallpack-submission/SUBMISSION_MANIFEST.md", names)
                self.assertIn("recallpack-submission/tools/public_repo_preflight.py", names)
                self.assertFalse(any(name.startswith("recallpack-submission/dist/") for name in names))
                self.assertFalse(any(name.startswith("recallpack-submission/docs/execution/") for name in names))
                self.assertNotIn("recallpack-submission/AGENTS.md", names)
                self.assertFalse(any("__pycache__" in name for name in names))
                manifest = json.loads(zip_file.read("EXTERNAL_REVIEW_MANIFEST.json"))
                prompt = zip_file.read("EXTERNAL_REVIEW_PROMPT.md").decode()

            self.assertEqual("RecallPack external review archive", manifest["title"])
            self.assertEqual("recallpack-submission", manifest["bundle_root"])
            self.assertEqual("sanitized_bundle", manifest["source_kind"])
            self.assertFalse(manifest["requires_credentials"])
            self.assertFalse(manifest["network_calls_made"])
            self.assertIn("adversarial hackathon judge", prompt)
            self.assertIn("fresh M98 live Qwen rerun is included as `live_e2e_failed`", prompt)
            self.assertIn("M104 credential-free runtime proof", prompt)

    def test_external_review_zip_rejects_raw_workspace(self):
        from tools.build_external_review_zip import build_external_review_zip

        with tempfile.TemporaryDirectory() as tmp:
            raw_like_workspace = Path(tmp) / "raw-workspace"
            raw_like_workspace.mkdir()
            (raw_like_workspace / "README.md").write_text("not a sanitized bundle\n")
            archive = Path(tmp) / "bad.zip"

            with self.assertRaises(ValueError):
                build_external_review_zip(raw_like_workspace, archive)

            self.assertFalse(archive.exists())

    def test_external_review_zip_rejects_symlinks_inside_bundle(self):
        from tools.build_external_review_zip import build_external_review_zip

        with tempfile.TemporaryDirectory() as tmp:
            bundle = Path(tmp) / "recallpack-submission"
            archive = Path(tmp) / "bad.zip"
            build_submission_bundle(ROOT, bundle)
            (bundle / "linked-readme.md").symlink_to(bundle / "README.md")

            with self.assertRaises(ValueError):
                build_external_review_zip(bundle, archive)

            self.assertFalse(archive.exists())

    def test_builds_public_bundle_with_required_files_and_manifest(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "recallpack-submission"

            result = build_submission_bundle(ROOT, target)

            self.assertEqual(target, result.target)
            self.assertTrue((target / ".gitignore").is_file())
            self.assertTrue((target / "README.md").is_file())
            self.assertTrue((target / "LICENSE").is_file())
            self.assertTrue((target / "requirements-v4.txt").is_file())
            self.assertTrue(
                (
                    target
                    / "specs"
                    / "001-recallpack-v4"
                    / "contracts"
                    / "artifacts.schema.json"
                ).is_file()
            )
            self.assertTrue(
                (
                    target
                    / "specs"
                    / "001-recallpack-v4"
                    / "contracts"
                    / "compile.openapi.yaml"
                ).is_file()
            )
            self.assertTrue(
                (
                    target
                    / "specs"
                    / "001-recallpack-v4"
                    / "contracts"
                    / "evaluation.schema.json"
                ).is_file()
            )
            for contract_name in (
                "review-seed.schema.json",
                "review-seed-contract.md",
                "review-json-golden-vectors.json",
            ):
                self.assertTrue(
                    (
                        target
                        / "specs"
                        / "001-recallpack-v4"
                        / "contracts"
                        / contract_name
                    ).is_file()
                )
            for authority_name in (
                "t053-external-review-phase2-prompt-v4.md",
                "t053-semantic-adjudication-vectors-v4.json",
                "t053-semantic-adjudication-report.schema.v4.json",
                "t053-phase2-custody-report.schema.v4.json",
                "t053-proposed-events-v3.json",
                "t053-review-source-inventory-v3.json",
            ):
                self.assertTrue(
                    (
                        target
                        / "specs"
                        / "001-recallpack-v4"
                        / "reviews"
                        / authority_name
                    ).is_file()
                )
            self.assertTrue(
                (
                    target
                    / "specs"
                    / "001-recallpack-v4"
                    / "contracts"
                    / "observe.openapi.yaml"
                ).is_file()
            )
            self.assertTrue((target / "src" / "recallpack" / "demo_server.py").is_file())
            self.assertTrue((target / "evaluation" / "Dockerfile").is_file())
            self.assertTrue(
                (target / "evaluation" / "runner" / "run_tests.py").is_file()
            )
            self.assertTrue((target / "tests" / "test_submission_docs.py").is_file())
            self.assertTrue((target / "fixtures" / "project-a" / "sessions.jsonl").is_file())
            self.assertTrue((target / "fixtures" / "project-b" / "sessions.jsonl").is_file())
            self.assertTrue(
                (target / "fixtures" / "project-b" / "repo_snapshot" / "src" / "config_loader.py").is_file()
            )
            self.assertTrue((target / "fixtures" / "project-c" / "sessions.jsonl").is_file())
            self.assertTrue(
                (target / "fixtures" / "project-c" / "repo_snapshot" / "src" / "cache_policy.py").is_file()
            )
            self.assertTrue((target / "fixtures" / "project-d" / "sessions.jsonl").is_file())
            self.assertTrue(
                (target / "fixtures" / "project-d" / "repo_snapshot" / "src" / "audit_serializer.py").is_file()
            )
            self.assertTrue((target / "fixtures" / "project-e" / "sessions.jsonl").is_file())
            self.assertTrue(
                (target / "fixtures" / "project-e" / "repo_snapshot" / "src" / "pagination.py").is_file()
            )
            self.assertTrue(
                (target / "fixtures" / "project-f-realistic" / "sessions.jsonl").is_file()
            )
            self.assertTrue(
                (
                    target
                    / "fixtures"
                    / "project-f-realistic"
                    / "repo_snapshot"
                    / "src"
                    / "api_client.py"
                ).is_file()
            )
            self.assertTrue(
                (target / "fixtures" / "project-g-auth-mode" / "sessions.jsonl").is_file()
            )
            self.assertTrue(
                (
                    target
                    / "fixtures"
                    / "project-g-auth-mode"
                    / "repo_snapshot"
                    / "src"
                    / "provider_auth.py"
                ).is_file()
            )
            self.assertTrue(
                (target / "fixtures" / "project-h-projectodyssey-jit" / "sessions.jsonl").is_file()
            )
            self.assertTrue(
                (
                    target
                    / "fixtures"
                    / "project-h-projectodyssey-jit"
                    / "repo_snapshot"
                    / "src"
                    / "ci_policy.py"
                ).is_file()
            )
            self.assertTrue((target / "web" / "index.html").is_file())
            self.assertTrue((target / "docs" / "submission" / "review-packet.md").is_file())
            self.assertTrue(
                (
                    target
                    / "docs"
                    / "submission"
                    / "projectodyssey-live-qwen-e2e-preflight.json"
                ).is_file()
            )
            self.assertTrue(
                (
                    target
                    / "docs"
                    / "submission"
                    / "projectodyssey-live-qwen-e2e-trace.json"
                ).is_file()
            )
            self.assertTrue(
                (target / "docs" / "submission" / "devpost-final-copy.md").is_file()
            )
            self.assertTrue(
                (target / "docs" / "submission" / "skeptical-judge-qa.md").is_file()
            )
            self.assertTrue(
                (target / "docs" / "submission" / "architecture-diagram.md").is_file()
            )
            self.assertTrue(
                (target / "docs" / "submission" / "public-release-gate.md").is_file()
            )
            self.assertTrue(
                (target / "docs" / "submission" / "demo-media-package.md").is_file()
            )
            self.assertTrue(
                (target / "docs" / "submission" / "devpost-upload-state.json").is_file()
            )
            self.assertTrue(
                (target / "docs" / "submission" / "media" / "README.md").is_file()
            )
            self.assertTrue(
                (
                    target
                    / "docs"
                    / "submission"
                    / "media"
                    / "alibaba-cloud-deployment-proof-redacted.png"
                ).is_file()
            )
            self.assertFalse(
                (
                    target
                    / "docs"
                    / "submission"
                    / "media"
                    / "alibaba-cloud-deployment-proof.png"
                ).exists()
            )
            self.assertTrue((target / "docs" / "deployment" / "alibaba-cloud-proof.md").is_file())
            self.assertTrue(
                (target / "docs" / "plans" / "2026-06-24-recallpack-v3.2.2.md").is_file()
            )
            self.assertTrue((target / "tools" / "judge_smoke.py").is_file())
            self.assertTrue((target / "tools" / "capture_demo_screenshots.py").is_file())
            self.assertTrue((target / "tools" / "devpost_preflight.py").is_file())
            self.assertTrue((target / "tools" / "export_devpost_materials.py").is_file())
            self.assertTrue((target / "tools" / "export_evidence_index.py").is_file())
            self.assertTrue((target / "tools" / "final_submission_gate.py").is_file())
            self.assertTrue((target / "tools" / "public_repo_preflight.py").is_file())
            self.assertTrue((target / "tools" / "build_external_review_zip.py").is_file())
            self.assertTrue((target / "deploy" / "alibaba-cloud" / "Dockerfile").is_file())

            manifest = (target / "SUBMISSION_MANIFEST.md").read_text()
            self.assertIn("# RecallPack Submission Bundle Manifest", manifest)
            self.assertIn(".gitignore", manifest)
            self.assertIn("README.md", manifest)
            self.assertIn("LICENSE", manifest)
            self.assertIn("docs/execution/", manifest)
            self.assertIn("__pycache__/", manifest)
            self.assertIn("## Judge Quick Checks", manifest)
            self.assertIn("MemoryAgent", manifest)
            self.assertIn("No credentials are required for local checks.", manifest)
            self.assertIn("PYTHONPATH=src python3 tools/build_live_qwen_e2e_preflight.py", manifest)
            self.assertIn(
                "PYTHONPATH=src python3 tools/build_live_qwen_embedding_baseline_preflight.py",
                manifest,
            )
            self.assertIn("PYTHONPATH=src python3 tools/fresh_clone_smoke.py --source .", manifest)
            self.assertIn("PYTHONPATH=src python3 tools/fresh_clone_smoke.py --source . --full", manifest)
            self.assertIn("python3 tools/devpost_preflight.py", manifest)
            self.assertIn("python3 tools/export_devpost_materials.py", manifest)
            self.assertIn("python3 tools/export_evidence_index.py", manifest)
            self.assertIn("python3 tools/final_submission_gate.py", manifest)
            self.assertIn("python3 tools/public_repo_preflight.py", manifest)
            self.assertIn("python3 tools/judge_smoke.py --url http://127.0.0.1:8789", manifest)
            self.assertIn("curl http://127.0.0.1:8789/api/health", manifest)
            self.assertIn("POST /observe", manifest)
            self.assertIn("POST /compile", manifest)

    def test_public_bundle_excludes_internal_and_generated_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "recallpack-submission"

            build_submission_bundle(ROOT, target)

            bundled_files = {path.relative_to(target).as_posix() for path in target.rglob("*")}
            self.assertNotIn("AGENTS.md", bundled_files)
            self.assertFalse(any(path.startswith("docs/execution/") for path in bundled_files))
            self.assertFalse(any("__pycache__" in path for path in bundled_files))
            self.assertFalse(any(path.endswith(".pyc") for path in bundled_files))
            self.assertFalse(any(path.endswith(".DS_Store") for path in bundled_files))
            self.assertNotIn(
                "docs/submission/media/recallpack-judge-deck.pptx.inspect.ndjson",
                bundled_files,
            )
            self.assertNotIn(
                "docs/submission/quality-hardening-audit.md",
                bundled_files,
            )
            self.assertNotIn(
                "docs/submission/winner-grade-benchmark-audit.md",
                bundled_files,
            )
            self.assertFalse(
                any(
                    path.startswith("docs/submission/m")
                    and "-external-" in path
                    for path in bundled_files
                )
            )
            self.assertFalse(
                any(path.startswith("docs/research/") for path in bundled_files)
            )
            self.assertNotIn(
                "docs/submission/media/alibaba-cloud-deployment-proof.png",
                bundled_files,
            )
            self.assertIn(
                "docs/submission/media/alibaba-cloud-deployment-proof-redacted.png",
                bundled_files,
            )

            scan = scan_submission_bundle(target)
            self.assertEqual([], scan["local_path_hits"])
            self.assertEqual([], scan["secret_hits"])
            self.assertEqual([], scan["generated_artifact_hits"])
            self.assertEqual([], scan["internal_path_hits"])

    def test_bundle_rewrites_self_referential_bundle_paths_to_target(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "dist" / "recallpack-submission-20990101-010203"

            build_submission_bundle(ROOT, target)

            expected = "dist/recallpack-submission-20990101-010203"
            stale_pattern = "dist/recallpack-submission-20260704-064732"
            checked_files = [
                "docs/submission/local-readiness-report.md",
                "docs/submission/final-judge-rehearsal.md",
                "docs/submission/recording-rehearsal-report.md",
                "docs/submission/recording-rehearsal-report.json",
                "docs/submission/devpost-materials.md",
                "docs/submission/devpost-materials.json",
                "docs/submission/evidence-index.json",
                "docs/submission/public-release-gate.md",
                "docs/submission/public-repo-readiness-report.md",
            ]
            for relative in checked_files:
                text = (target / relative).read_text()
                self.assertIn(expected, text, msg=relative)
                self.assertNotIn(stale_pattern, text, msg=relative)

    def test_bundle_reference_rewrite_preserves_historical_ecs_proof_bundle(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "dist" / "recallpack-submission-20990101-070809"

            build_submission_bundle(ROOT, target)

            report = (target / "docs" / "submission" / "public-repo-readiness-report.md").read_text()
            self.assertIn("dist/recallpack-submission-20260704-123846", report)
            self.assertIn("M104 credential-free runtime built from the", report)

    def test_bundle_reference_rewrite_does_not_mutate_python_tests(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "dist" / "recallpack-submission-20990101-040506"

            build_submission_bundle(ROOT, target)

            copied_test = (target / "tests" / "test_submission_bundle.py").read_text()
            self.assertIn(
                'expected = "dist/recallpack-submission-20990101-010203"',
                copied_test,
            )

    def test_non_timestamped_test_bundle_does_not_rewrite_release_paths(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "recallpack-submission"

            build_submission_bundle(ROOT, target)

            report = (target / "docs" / "submission" / "local-readiness-report.md").read_text()
            self.assertRegex(report, r"dist/recallpack-submission-[0-9]{8}-[0-9]{6}")
            self.assertNotIn("Latest generated local bundle:\n  `recallpack-submission/`", report)

    def test_m93_judge_first_run_commands_are_shared_across_public_surfaces(self):
        from tools.public_repo_preflight import build_public_repo_preflight

        readme = (ROOT / "README.md").read_text()
        review_packet = (ROOT / "docs" / "submission" / "review-packet.md").read_text()
        self.assertTrue(hasattr(submission_bundle, "JUDGE_FIRST_RUN_COMMANDS"))
        judge_commands = submission_bundle.JUDGE_FIRST_RUN_COMMANDS

        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "recallpack-submission"
            build_submission_bundle(ROOT, target)
            manifest = (target / "SUBMISSION_MANIFEST.md").read_text()
            preflight = build_public_repo_preflight(target)

        self.assertIn("python3 tools/video_rehearsal_gate.py", judge_commands)
        self.assertIn("python3 tools/export_devpost_materials.py", judge_commands)
        self.assertIn("node --check web/app.js", judge_commands)
        self.assertIn("python3 -m venv .venv", judge_commands)
        self.assertIn("python3 -m pip install -r requirements-v4.txt", judge_commands)
        self.assertEqual(list(judge_commands), preflight["judge_commands"])

        for command in judge_commands:
            self.assertIn(command, manifest)
            self.assertIn(command, readme)
            self.assertIn(command, review_packet)

    def test_fresh_clone_public_surface_requires_judge_facing_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            clone = Path(tmp) / "incomplete-public-repo"
            clone.mkdir()

            with self.assertRaisesRegex(AssertionError, "missing required public files"):
                _assert_public_surface(clone)

    def test_fresh_clone_public_surface_requires_manifest_quick_checks(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "recallpack-submission"
            build_submission_bundle(ROOT, target)
            (target / "SUBMISSION_MANIFEST.md").write_text(
                "# RecallPack Submission Bundle Manifest\n\n## Included Files\n",
                encoding="utf-8",
            )

            with self.assertRaisesRegex(AssertionError, "manifest is missing judge quick checks"):
                _assert_public_surface(target)

    def test_fresh_clone_public_surface_rejects_stale_static_demo_data(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "recallpack-submission"
            build_submission_bundle(ROOT, target)
            (target / "web" / "demo-data.js").write_text(
                'window.RECALLPACK_DEMO_DATA = {"title": "stale"};\n',
                encoding="utf-8",
            )

            with self.assertRaisesRegex(AssertionError, "static demo data is stale"):
                _assert_public_surface(target)

    def test_fresh_clone_requires_exact_installed_dependency_versions(self):
        with tempfile.TemporaryDirectory() as tmp:
            clone = Path(tmp)
            (clone / "requirements-v4.txt").write_text(
                "jsonschema==4.26.0\nPyYAML==6.0.3\ntiktoken==0.13.0\n",
                encoding="utf-8",
            )

            installed = {
                "jsonschema": "4.26.0",
                "pyyaml": "6.0.3",
                "tiktoken": "0.12.0",
            }
            with patch.object(
                fresh_clone_smoke.metadata,
                "version",
                side_effect=lambda name: installed[name.casefold()],
            ):
                with self.assertRaisesRegex(
                    AssertionError,
                    "runtime dependency version mismatch.*tiktoken",
                ):
                    _assert_runtime_dependencies(clone)

    def test_fresh_clone_requires_o200k_base_runtime_encoding(self):
        with tempfile.TemporaryDirectory() as tmp:
            clone = Path(tmp)
            (clone / "requirements-v4.txt").write_text(
                "jsonschema==4.26.0\nPyYAML==6.0.3\ntiktoken==0.13.0\n",
                encoding="utf-8",
            )

            installed = {
                "jsonschema": "4.26.0",
                "pyyaml": "6.0.3",
                "tiktoken": "0.13.0",
            }
            with (
                patch.object(
                    fresh_clone_smoke.metadata,
                    "version",
                    side_effect=lambda name: installed[name.casefold()],
                ),
                patch.object(
                    fresh_clone_smoke,
                    "_load_runtime_encoding_name",
                    return_value="cl100k_base",
                ),
            ):
                with self.assertRaisesRegex(
                    AssertionError,
                    "runtime tokenizer mismatch.*o200k_base",
                ):
                    _assert_runtime_dependencies(clone)

    def test_fresh_clone_reports_unavailable_runtime_tokenizer(self):
        with tempfile.TemporaryDirectory() as tmp:
            clone = Path(tmp)
            (clone / "requirements-v4.txt").write_text(
                "jsonschema==4.26.0\nPyYAML==6.0.3\ntiktoken==0.13.0\n",
                encoding="utf-8",
            )

            installed = {
                "jsonschema": "4.26.0",
                "pyyaml": "6.0.3",
                "tiktoken": "0.13.0",
            }
            with (
                patch.object(
                    fresh_clone_smoke.metadata,
                    "version",
                    side_effect=lambda name: installed[name.casefold()],
                ),
                patch.object(
                    fresh_clone_smoke,
                    "_load_runtime_encoding_name",
                    side_effect=RuntimeError("broken encoding cache"),
                ),
            ):
                with self.assertRaisesRegex(
                    AssertionError,
                    "runtime tokenizer unavailable.*o200k_base",
                ):
                    _assert_runtime_dependencies(clone)

    def test_fresh_clone_accepts_current_pinned_runtime(self):
        _assert_runtime_dependencies(ROOT)

    def test_builder_refuses_existing_target_by_default(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "recallpack-submission"
            target.mkdir()

            with self.assertRaises(FileExistsError):
                build_submission_bundle(ROOT, target)

    def test_secret_scan_ignores_safe_variable_names_but_flags_real_tokens(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "scan-target"
            target.mkdir()
            (target / "safe.py").write_text(
                'api_key = os.environ.get("DASHSCOPE_API_KEY", "")\n'
                'client = Client(api_key=api_key)\n'
                'placeholder = "unit-secret"\n'
            )
            (target / "unsafe.txt").write_text(
                "token " + "sk-" + "1234567890abcdefghijklmnopqrstuvwxyz\n"
            )

            scan = scan_submission_bundle(target)

        self.assertEqual([], scan["local_path_hits"])
        self.assertEqual([], scan["generated_artifact_hits"])
        self.assertEqual([], scan["internal_path_hits"])
        self.assertEqual(
            ["unsafe.txt:sk-[A-Za-z0-9_-]{20,}"],
            scan["secret_hits"],
        )

    def test_fresh_clone_smoke_rehearses_bundle_from_temp_copy(self):
        if os.environ.get("RECALLPACK_FRESH_CLONE_CHILD") == "1":
            self.skipTest("fresh-clone child run skips recursive fresh-clone smoke tests")
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "recallpack-submission"
            build_submission_bundle(ROOT, target)
            env = dict(os.environ)
            env["PYTHONPATH"] = str(ROOT / "src")

            result = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "tools" / "fresh_clone_smoke.py"),
                    "--source",
                    str(target),
                ],
                cwd=ROOT,
                env=env,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=45,
            )

        self.assertEqual(
            0,
            result.returncode,
            msg=f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}",
        )
        self.assertIn('"status": "passed"', result.stdout)
        self.assertIn('"copied_to_temp": true', result.stdout)
        self.assertIn('"judge_smoke": "passed"', result.stdout)

    def test_public_bundle_root_can_self_rehearse_with_source_dot(self):
        if os.environ.get("RECALLPACK_FRESH_CLONE_CHILD") == "1":
            self.skipTest("fresh-clone child run skips recursive fresh-clone smoke tests")
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "recallpack-submission"
            build_submission_bundle(ROOT, target)
            env = dict(os.environ)
            env["PYTHONPATH"] = "src"

            result = subprocess.run(
                [
                    sys.executable,
                    "tools/fresh_clone_smoke.py",
                    "--source",
                    ".",
                ],
                cwd=target,
                env=env,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=45,
            )

            self.assertEqual(
                0,
                result.returncode,
                msg=f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}",
            )
            self.assertIn('"status": "passed"', result.stdout)
            self.assertIn('"copied_to_temp": true', result.stdout)
            self.assertIn('"judge_smoke": "passed"', result.stdout)
            self.assertEqual([], scan_submission_bundle(target)["generated_artifact_hits"])
            self.assertFalse((target / "src" / "recallpack" / "__pycache__").exists())

    def test_fresh_clone_smoke_full_mode_uses_full_nonrecursive_unittest_discovery(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "source"
            source.mkdir()
            commands = []

            def record_run(command, cwd, env, timeout):
                commands.append(command)
                return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

            with (
                patch.object(fresh_clone_smoke, "_assert_public_surface"),
                patch.object(fresh_clone_smoke, "_run", side_effect=record_run),
                patch.object(
                    fresh_clone_smoke,
                    "_run_server_smoke",
                    return_value={"status": "passed"},
                ),
            ):
                result = fresh_clone_smoke.run_fresh_clone_smoke(source, full=True)

        self.assertEqual("passed", result["status"])
        self.assertEqual("full", result["unit_mode"])
        self.assertEqual("passed", result["checks"]["unit_full"])
        self.assertTrue(
            any(
                command[1:] == ["-m", "unittest", "discover", "-s", "tests", "-v"]
                for command in commands
            ),
            msg=commands,
        )

    def test_fresh_clone_server_smoke_closes_server_output_pipes(self):
        class FakePipe:
            def __init__(self):
                self.closed = False

            def close(self):
                self.closed = True

        class FakeServer:
            def __init__(self):
                self.stdout = FakePipe()
                self.stderr = FakePipe()

            def terminate(self):
                return None

            def wait(self, timeout):
                return 0

        server = FakeServer()
        completed = subprocess.CompletedProcess(
            ["judge-smoke"],
            0,
            stdout='{"status": "passed"}',
        )
        with (
            patch.object(fresh_clone_smoke.subprocess, "Popen", return_value=server),
            patch.object(fresh_clone_smoke, "_wait_for_server"),
            patch.object(fresh_clone_smoke, "_run", return_value=completed),
        ):
            result = fresh_clone_smoke._run_server_smoke(
                ROOT,
                env={},
                port=8789,
                timeout=1,
            )

        self.assertEqual({"status": "passed"}, result)
        self.assertTrue(server.stdout.closed)
        self.assertTrue(server.stderr.closed)

    def test_fresh_clone_child_env_marks_recursive_rehearsal_context(self):
        with tempfile.TemporaryDirectory() as tmp:
            temp_root = Path(tmp)
            env = _fresh_env(temp_root / "repo", temp_root)

        self.assertEqual("1", env["RECALLPACK_FRESH_CLONE_CHILD"])

    def test_fresh_clone_copy_excludes_vcs_metadata(self):
        ignored = _ignore_runtime_artifacts(
            "/tmp/source",
            [".git", ".DS_Store", "module.pyc", "recallpack.sqlite3", "README.md"],
        )

        self.assertIn(".git", ignored)
        self.assertIn(".DS_Store", ignored)
        self.assertIn("module.pyc", ignored)
        self.assertIn("recallpack.sqlite3", ignored)
        self.assertNotIn("README.md", ignored)


if __name__ == "__main__":
    unittest.main()
