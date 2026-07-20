import copy
import hashlib
import unittest
import json
import shutil
import subprocess
import tempfile
from dataclasses import asdict
from pathlib import Path

import recallpack.evaluation as evaluation_module
import recallpack.isolation as isolation_module
from recallpack.evaluation import (
    evaluate_hero_fixture,
    load_hero_fixture,
    run_downstream_proof,
    validate_downstream_files,
)
from recallpack.evidence import (
    validate_aggregate_report,
    validate_evaluation_run,
    validate_evidence_manifest,
    validate_execution_manifest,
)
from recallpack.evidence_authority import TestOnlyTrustedRetainedAttemptLoader
from recallpack.budget import canonical_json
from recallpack.downstream import (
    PatchGenerationRequest,
    PatchGenerationResult,
    _allowed_source_files,
    _patch_generation_prompt,
)
from recallpack.providers import ProviderTrace, TEXT_MODEL
from tests.v4_evidence_fixtures import (
    V4_VARIANTS,
    build_artifact_bytes,
    build_attempt_summary,
    build_floor_execution_manifest,
    build_floor_runner_output_loader,
    build_floor_runner_payloads,
    build_relation_label_ledger,
    build_source_ledger,
    canonical_sha256,
    definition_validator,
)


FIXTURE_ROOT = Path(__file__).resolve().parents[1] / "fixtures" / "project-a"
SECOND_FIXTURE_ROOT = Path(__file__).resolve().parents[1] / "fixtures" / "project-b"
THIRD_FIXTURE_ROOT = Path(__file__).resolve().parents[1] / "fixtures" / "project-c"
FOURTH_FIXTURE_ROOT = Path(__file__).resolve().parents[1] / "fixtures" / "project-d"
FIFTH_FIXTURE_ROOT = Path(__file__).resolve().parents[1] / "fixtures" / "project-e"
REALISTIC_FIXTURE_ROOT = Path(__file__).resolve().parents[1] / "fixtures" / "project-f-realistic"
AUTH_MODE_FIXTURE_ROOT = Path(__file__).resolve().parents[1] / "fixtures" / "project-g-auth-mode"
PROJECT_ODYSSEY_FIXTURE_ROOT = (
    Path(__file__).resolve().parents[1] / "fixtures" / "project-h-projectodyssey-jit"
)


def _receipted_floor_output(manifest, slot, output):
    manifest_sha256 = canonical_sha256(manifest)
    identity = isolation_module.ProductionExecutionIdentity(
        execution_manifest_sha256=manifest_sha256,
        scenario_id=slot["scenario_slot"],
        slot_index=slot["slot_index"],
        attempt_no=slot["repetition"],
        repository_snapshot_sha256="b" * 64,
        hidden_test_tree_sha256="c" * 64,
    )
    output["test_result"]["tests"] = [
        {
            "name": "network_probe",
            "status": "passed",
            "duration_ms": 1,
            "evidence_artifact_id": "runner_result_json",
        },
        {
            "name": "test_runtime_contract",
            "status": "passed" if output["full_suite_passed"] else "failed",
            "duration_ms": 1,
            "evidence_artifact_id": "runner_result_json",
        },
    ]
    output["test_result"]["passed"] = sum(
        test["status"] == "passed" for test in output["test_result"]["tests"]
    )
    output["test_result"]["failed"] = sum(
        test["status"] == "failed" for test in output["test_result"]["tests"]
    )
    output["test_result"]["exit_code"] = 0 if output["full_suite_passed"] else 1
    payload_text = json.dumps(
        output["test_result"],
        sort_keys=True,
        separators=(",", ":"),
    )

    class CompletedDockerRunner:
        def __call__(self, argv, *, env, timeout, capture_output, text, check):
            del env, timeout, capture_output, text, check
            return subprocess.CompletedProcess(
                args=argv,
                returncode=output["test_result"]["exit_code"],
                stdout=payload_text,
                stderr="",
            )

    runner = CompletedDockerRunner()
    contract = manifest["evaluator_contract"]
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir).resolve()
        repository_root = root / "repo"
        hidden_test_root = root / "hidden"
        repository_root.mkdir()
        hidden_test_root.mkdir()
        repository_root = repository_root.resolve()
        hidden_test_root = hidden_test_root.resolve()
        container_name = f"recallpack-eval-{slot['slot_index']}"
        argv, _ = isolation_module.build_docker_argv(
            evaluator_contract=contract,
            image_digest=contract["image_digest"],
            repository_root=repository_root,
            hidden_test_root=hidden_test_root,
            command=isolation_module.SAFE_COMMAND,
            container_name=container_name,
        )
        patch_sha256 = canonical_sha256(output["patched_files"])
        binding = isolation_module.IsolatedExecutionBinding(
            variant_id=slot["variant_id"],
            patch_sha256=patch_sha256,
            repository_tree_sha256="d" * 64,
            hidden_test_tree_sha256=identity.hidden_test_tree_sha256,
            execution_nonce=f"receipt-{slot['slot_index']}",
            docker_argv_sha256=isolation_module.execution_invocation_sha256(
                argv=argv,
                variant_id=slot["variant_id"],
                patch_sha256=patch_sha256,
                repository_tree_sha256="d" * 64,
                hidden_test_tree_sha256=identity.hidden_test_tree_sha256,
                execution_nonce=f"receipt-{slot['slot_index']}",
                production_identity=identity,
            ),
            authority_mode="production_docker",
            execution_manifest_sha256=identity.execution_manifest_sha256,
            scenario_id=identity.scenario_id,
            slot_index=identity.slot_index,
            attempt_no=identity.attempt_no,
            repository_snapshot_sha256=identity.repository_snapshot_sha256,
            frozen_hidden_test_tree_sha256=identity.hidden_test_tree_sha256,
        )
        original_run = isolation_module.subprocess.run
        isolation_module.subprocess.run = runner
        try:
            isolated_result = isolation_module.run_isolated_suite(
                evaluator_contract=contract,
                image_digest=contract["image_digest"],
                repository_root=repository_root,
                hidden_test_root=hidden_test_root,
                command=isolation_module.SAFE_COMMAND,
                docker_runner=runner,
                docker_cleanup_runner=runner,
                container_name=container_name,
                execution_binding=binding,
            )
        finally:
            isolation_module.subprocess.run = original_run
    output["stdout"] = isolated_result.stdout
    output["stderr"] = isolated_result.stderr
    output["test_result"] = copy.deepcopy(isolated_result.json_result)
    output["runtime_trace"]["execution_binding"] = asdict(binding)
    return isolated_result, identity


def _receipted_floor_technical_failure(manifest, slot, output):
    manifest_sha256 = canonical_sha256(manifest)
    identity = isolation_module.ProductionExecutionIdentity(
        execution_manifest_sha256=manifest_sha256,
        scenario_id=slot["scenario_slot"],
        slot_index=slot["slot_index"],
        attempt_no=slot["repetition"],
        repository_snapshot_sha256="b" * 64,
        hidden_test_tree_sha256="c" * 64,
    )

    class UnavailableDockerRunner:
        def __call__(self, argv, *, env, timeout, capture_output, text, check):
            del env, timeout, capture_output, text, check
            return subprocess.CompletedProcess(
                args=argv,
                returncode=125,
                stdout="",
                stderr="docker daemon unavailable",
            )

    runner = UnavailableDockerRunner()
    contract = manifest["evaluator_contract"]
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir).resolve()
        repository_root = root / "repo"
        hidden_test_root = root / "hidden"
        repository_root.mkdir()
        hidden_test_root.mkdir()
        repository_root = repository_root.resolve()
        hidden_test_root = hidden_test_root.resolve()
        container_name = f"recallpack-eval-failure-{slot['slot_index']}"
        argv, _ = isolation_module.build_docker_argv(
            evaluator_contract=contract,
            image_digest=contract["image_digest"],
            repository_root=repository_root,
            hidden_test_root=hidden_test_root,
            command=isolation_module.SAFE_COMMAND,
            container_name=container_name,
        )
        patch_sha256 = canonical_sha256(output["patched_files"])
        binding = isolation_module.IsolatedExecutionBinding(
            variant_id=slot["variant_id"],
            patch_sha256=patch_sha256,
            repository_tree_sha256="d" * 64,
            hidden_test_tree_sha256=identity.hidden_test_tree_sha256,
            execution_nonce=f"failure-receipt-{slot['slot_index']}",
            docker_argv_sha256=isolation_module.execution_invocation_sha256(
                argv=argv,
                variant_id=slot["variant_id"],
                patch_sha256=patch_sha256,
                repository_tree_sha256="d" * 64,
                hidden_test_tree_sha256=identity.hidden_test_tree_sha256,
                execution_nonce=f"failure-receipt-{slot['slot_index']}",
                production_identity=identity,
            ),
            authority_mode="production_docker",
            execution_manifest_sha256=identity.execution_manifest_sha256,
            scenario_id=identity.scenario_id,
            slot_index=identity.slot_index,
            attempt_no=identity.attempt_no,
            repository_snapshot_sha256=identity.repository_snapshot_sha256,
            frozen_hidden_test_tree_sha256=identity.hidden_test_tree_sha256,
        )
        original_run = isolation_module.subprocess.run
        isolation_module.subprocess.run = runner
        try:
            isolated_result = isolation_module.run_isolated_suite(
                evaluator_contract=contract,
                image_digest=contract["image_digest"],
                repository_root=repository_root,
                hidden_test_root=hidden_test_root,
                command=isolation_module.SAFE_COMMAND,
                docker_runner=runner,
                docker_cleanup_runner=runner,
                container_name=container_name,
                execution_binding=binding,
            )
        finally:
            isolation_module.subprocess.run = original_run
    output.update(
        {
            "full_suite_passed": None,
            "stdout": isolated_result.stdout,
            "stderr": isolated_result.stderr,
            "test_result": None,
            "runtime_trace": {
                **output["runtime_trace"],
                "execution_binding": asdict(binding),
            },
            "attempt_outcome": {
                "status": "invalidated",
                "stage": "sandbox",
                "code": "technical_failure",
            },
            "failure": {
                "code": isolated_result.failure_code,
                "detail": (
                    "isolated evaluator did not produce a closed test result; "
                    f"cleanup_attempted={isolated_result.cleanup_attempted}; "
                    f"cleanup_succeeded={isolated_result.cleanup_succeeded}"
                ),
                "evidence_sha256": hashlib.sha256(
                    (isolated_result.stdout + "\n" + isolated_result.stderr).encode(
                        "utf-8"
                    )
                ).hexdigest(),
            },
        }
    )
    return isolated_result, identity


class MissingRetryPatchProvider:
    def generate_patch(self, request):
        return PatchGenerationResult(
            files=[{"path": "src/retry.py", "content": "def not_retry():\n    return None\n"}],
            trace=ProviderTrace(
                provider_name="fake-qwen",
                model_id=TEXT_MODEL,
                provider_role="patch_generation",
                request_purpose="generate_patch_from_goal_and_selected_context",
                input_item_count=1 + len(request.selected_context),
                input_token_estimate=1,
                output_item_count=1,
                request_id="missing-retry",
            ),
        )


class UnapprovedPathPatchProvider:
    def generate_patch(self, request):
        return PatchGenerationResult(
            files=[{"path": "README.md", "content": "leak"}],
            trace=ProviderTrace(
                provider_name="fake-qwen",
                model_id=TEXT_MODEL,
                provider_role="patch_generation",
                request_purpose="generate_patch_from_goal_and_selected_context",
                input_item_count=1 + len(request.selected_context),
                input_token_estimate=1,
                output_item_count=1,
                request_id="unapproved-path",
            ),
        )


class CapturingPatchProvider:
    def __init__(self):
        self.requests = []

    def generate_patch(self, request):
        self.requests.append(request)
        return PatchGenerationResult(
            files=[
                {
                    "path": "src/ci_policy.py",
                    "content": (
                        "def handle_jit_crash(error_message):\n"
                        "    return {\n"
                        "        \"action\": \"fail_and_fix_forward\",\n"
                        "        \"retry\": False,\n"
                        "        \"retry_attempts\": 0,\n"
                        "        \"continue_on_error\": False,\n"
                        "        \"skip\": False,\n"
                        "        \"minimal_reproducer_required\": True,\n"
                        "    }\n"
                    ),
                }
            ],
            trace=ProviderTrace(
                provider_name="fake-qwen",
                model_id=TEXT_MODEL,
                provider_role="patch_generation",
                request_purpose="generate_patch_from_goal_and_selected_context",
                input_item_count=1 + len(request.selected_context),
                input_token_estimate=1,
                output_item_count=1,
                request_id="captured-source-files",
                usage={
                    "source_file_paths": [
                        file.get("path", "") for file in request.source_files
                    ]
                },
            ),
        )


class HeroEvaluationTests(unittest.TestCase):
    def test_v3_fixture_evidence_cannot_satisfy_v4_headline_contract(self):
        fixture = load_hero_fixture(FIXTURE_ROOT)
        result = evaluate_hero_fixture(FIXTURE_ROOT)

        self.assertIn("goal", fixture.gold)
        self.assertFalse(hasattr(result, "execution_manifest_sha256"))
        self.assertFalse(hasattr(result, "evidence_manifest_id"))
        for variant in result.variants.values():
            patch_trace = variant.downstream["patch_generation"]
            self.assertFalse(patch_trace["is_live"])
            self.assertEqual(
                patch_trace["deterministic_fallback_status"],
                "fake_provider_deterministic",
            )
            for trace in variant.compile_trace.get("provider_traces", []):
                self.assertFalse(trace["is_live"])
                self.assertEqual(
                    trace["deterministic_fallback_status"],
                    "fake_provider_deterministic",
                )

    def test_hero_fixture_has_required_shape_without_repo_policy_leak(self):
        fixture = load_hero_fixture(FIXTURE_ROOT)

        self.assertGreaterEqual(len(fixture.events), 12)
        self.assertLessEqual(len(fixture.events), 16)
        self.assertEqual(fixture.gold["goal"], "Update the retry helper to follow the project's current retry policy.")
        retry_source = (FIXTURE_ROOT / "repo_snapshot" / "src" / "retry.py").read_text()
        readme_source = (FIXTURE_ROOT / "repo_snapshot" / "README.md").read_text()
        self.assertIn("max_attempts=3", retry_source)
        self.assertNotIn("five attempts", retry_source.lower())
        self.assertNotIn("exponential", retry_source.lower())
        self.assertNotIn("five attempts", readme_source.lower())
        self.assertNotIn("exponential", readme_source.lower())

    def test_hero_evaluator_shows_recallpack_filters_stale_memory(self):
        result = evaluate_hero_fixture(FIXTURE_ROOT)

        raw_rag = result.variants["embedding_top_k_rag"]
        recallpack = result.variants["recallpack"]

        self.assertGreater(raw_rag.metrics["stale_leakage_rate"], 0)
        self.assertLess(raw_rag.metrics["hidden_test_pass_count"], 3)
        self.assertEqual(recallpack.metrics["required_memory_recall_at_budget"], 1.0)
        self.assertEqual(recallpack.metrics["stale_leakage_rate"], 0.0)
        self.assertEqual(recallpack.metrics["hidden_test_pass_count"], 3)
        self.assertLessEqual(recallpack.metrics["memory_segment_tokens"], 512)
        self.assertEqual(
            [item["source_ref"] for item in recallpack.selected_context],
            ["session-a:turn-005", "session-a:turn-003"],
        )

    def test_hero_evaluator_includes_raw_full_history_and_computed_embedding_baseline(self):
        result = evaluate_hero_fixture(FIXTURE_ROOT)

        self.assertEqual(
            list(result.variants),
            ["raw_full_history", "embedding_top_k_rag", "recallpack"],
        )

        raw_full_history = result.variants["raw_full_history"]
        embedding_rag = result.variants["embedding_top_k_rag"]

        self.assertEqual(len(raw_full_history.selected_context), 12)
        self.assertEqual(
            raw_full_history.compile_trace["selection_source"],
            "raw_full_history_unfiltered",
        )
        self.assertFalse(raw_full_history.compile_trace["budget_comparable"])
        self.assertIn("session-a:turn-001", [item["source_ref"] for item in raw_full_history.selected_context])
        self.assertIn("session-a:turn-005", [item["source_ref"] for item in raw_full_history.selected_context])

        self.assertEqual(
            embedding_rag.compile_trace["selection_source"],
            "computed_embedding_top_k_raw_events",
        )
        self.assertEqual(
            embedding_rag.compile_trace["retrieval_mode"],
            "embedding_top_n_rerank_raw_history",
        )
        self.assertEqual(embedding_rag.compile_trace["embedding_top_k"], 2)
        self.assertEqual(embedding_rag.compile_trace["embedding_top_n_count"], 4)
        selected_sources = [item["source_ref"] for item in embedding_rag.selected_context]
        self.assertEqual(len(selected_sources), 2)
        self.assertIn("session-a:turn-001", selected_sources)
        self.assertNotIn("session-a:turn-005", selected_sources)
        self.assertEqual(embedding_rag.downstream["summary"]["passed"], 1)
        trace_roles = [
            record["provider_role"]
            for record in embedding_rag.compile_trace["provider_traces"]
        ]
        self.assertIn("embedding", trace_roles)

    def test_embedding_baseline_does_not_read_gold_selected_source_ids(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            copied = Path(temp_dir) / "project-a"
            shutil.copytree(FIXTURE_ROOT, copied)
            gold_path = copied / "gold.json"
            gold = json.loads(gold_path.read_text())
            gold["raw_history_rag_selected_sources"] = ["session-a:turn-012"]
            gold_path.write_text(json.dumps(gold, indent=2))

            result = evaluate_hero_fixture(copied)

        embedding_rag = result.variants["embedding_top_k_rag"]
        selected_sources = [item["source_ref"] for item in embedding_rag.selected_context]
        self.assertIn("session-a:turn-001", selected_sources)
        self.assertNotIn("session-a:turn-005", selected_sources)

    def test_hero_evaluator_uses_embedding_top_n_before_rerank_for_recallpack(self):
        result = evaluate_hero_fixture(FIXTURE_ROOT)

        trace = result.variants["recallpack"].compile_trace
        trace_roles = [record["provider_role"] for record in trace["provider_traces"]]

        self.assertEqual(trace["retrieval_mode"], "embedding_top_n")
        self.assertEqual(trace["embedding_top_n_count"], 2)
        self.assertEqual(trace["selected_count"], 2)
        self.assertIn("embedding", trace_roles)
        self.assertIn("rerank", trace_roles)
        self.assertEqual(trace["omitted_by_embedding_memory_ids"], [])

    def test_hero_evaluator_runs_downstream_patch_and_hidden_tests(self):
        result = evaluate_hero_fixture(FIXTURE_ROOT)

        raw_rag = result.variants["embedding_top_k_rag"].downstream
        recallpack = result.variants["recallpack"].downstream

        self.assertEqual(raw_rag["execution_mode"], "temp_repo_hidden_tests")
        self.assertEqual(recallpack["execution_mode"], "temp_repo_hidden_tests")
        self.assertEqual(raw_rag["summary"]["passed"], 1)
        self.assertEqual(raw_rag["summary"]["failed"], 2)
        self.assertEqual(recallpack["summary"]["passed"], 3)
        self.assertEqual(recallpack["summary"]["failed"], 0)
        self.assertIn("max_attempts=3", raw_rag["patch_diff"])
        self.assertIn("time.sleep(delay_seconds)", raw_rag["patch_diff"])
        self.assertIn("max_attempts=5", recallpack["patch_diff"])
        self.assertIn("time.sleep(delay_seconds * (2 ** attempt))", recallpack["patch_diff"])
        self.assertIn("stale retry policy", raw_rag["causal_reason"])
        self.assertIn("active retry policy", recallpack["causal_reason"])

    def test_downstream_proof_uses_context_text_not_source_ids(self):
        fixture = load_hero_fixture(FIXTURE_ROOT)
        misleading_context = [
            {
                "id": "misleading_current_source",
                "type": "decision",
                "subject": "retry_policy",
                "text": "Use three attempts with a fixed 100 ms delay.",
                "scope": "component:retry",
                "source_ref": "session-a:turn-005",
            },
            {
                "id": "dependency_preference",
                "type": "preference",
                "subject": "dependency_policy",
                "text": "Do not add new dependencies.",
                "scope": "project",
                "source_ref": "session-a:turn-003",
            },
        ]

        proof = run_downstream_proof(fixture, misleading_context, variant_id="misleading")

        self.assertEqual(proof["summary"]["passed"], 1)
        self.assertIn("max_attempts=3", proof["patch_diff"])
        self.assertIn("stale retry policy", proof["causal_reason"])

    def test_downstream_patch_generator_does_not_read_gold_patch_variants(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            copied = Path(temp_dir) / "project-b"
            shutil.copytree(SECOND_FIXTURE_ROOT, copied)
            gold_path = copied / "gold.json"
            gold = json.loads(gold_path.read_text())
            gold["patch_variants"]["current"] = [
                {
                    "path": "src/config_loader.py",
                    "content": "def get_required_config(config, key):\n    return None\n",
                }
            ]
            gold_path.write_text(json.dumps(gold, indent=2))

            result = evaluate_hero_fixture(copied)

        recallpack_downstream = result.variants["recallpack"].downstream
        self.assertEqual(recallpack_downstream["summary"], {"passed": 3, "failed": 0})
        self.assertIn("class ConfigError", recallpack_downstream["patch_diff"])
        self.assertEqual(
            recallpack_downstream["patch_generation"]["provider_role"],
            "patch_generation",
        )
        self.assertFalse(recallpack_downstream["patch_generation"]["used_gold_patch_variants"])
        self.assertNotIn(
            "patch_variants",
            recallpack_downstream["patch_generation"]["input_fields"],
        )

    def test_embedding_baseline_uses_same_provider_retrieval_and_patch_generator_contract(self):
        result = evaluate_hero_fixture(FIXTURE_ROOT)

        baseline = result.variants["embedding_top_k_rag"]
        recallpack = result.variants["recallpack"]
        baseline_trace_roles = [
            record["provider_role"]
            for record in baseline.compile_trace["provider_traces"]
        ]
        recallpack_trace_roles = [
            record["provider_role"]
            for record in recallpack.compile_trace["provider_traces"]
        ]

        self.assertEqual(
            baseline.compile_trace["retrieval_mode"],
            "embedding_top_n_rerank_raw_history",
        )
        self.assertEqual(baseline.compile_trace["embedding_top_n_count"], 4)
        self.assertEqual(baseline.compile_trace["rerank_input_count"], 4)
        self.assertIn("embedding", baseline_trace_roles)
        self.assertIn("rerank", baseline_trace_roles)
        self.assertIn("embedding", recallpack_trace_roles)
        self.assertIn("rerank", recallpack_trace_roles)
        self.assertEqual(
            baseline.downstream["patch_generation"]["model_name"],
            recallpack.downstream["patch_generation"]["model_name"],
        )
        self.assertEqual(
            baseline.downstream["patch_generation"]["provider_role"],
            recallpack.downstream["patch_generation"]["provider_role"],
        )
        self.assertEqual(
            baseline.downstream["patch_generation"]["request_purpose"],
            "generate_patch_from_goal_and_selected_context",
        )
        self.assertEqual(
            recallpack.downstream["patch_generation"]["request_purpose"],
            "generate_patch_from_goal_and_selected_context",
        )

    def test_live_patch_generation_prompt_guides_allowed_source_only_edits(self):
        prompt = _patch_generation_prompt(
            PatchGenerationRequest(
                goal="Fix the flaky Mojo JIT CI crash by updating retry handling.",
                selected_context=[
                    {
                        "type": "decision",
                        "subject": "ci_policy",
                        "scope": "component:ci_policy",
                        "source_ref": "session-h-current:turn-006",
                        "text": "Treat JIT crashes as real bugs; fail and fix forward.",
                    },
                    {
                        "type": "preference",
                        "subject": "dependency_policy",
                        "scope": "project",
                        "source_ref": "session-h-history:turn-004",
                        "text": "Do not add new dependencies for CI or test-runner fixes.",
                    },
                ],
                allowed_paths=["src/ci_policy.py", "pyproject.toml"],
                source_files=[
                    {
                        "path": "src/ci_policy.py",
                        "content": (
                            "def handle_jit_crash(error_message):\n"
                            "    return {\"minimal_reproducer_required\": False}\n"
                        ),
                    }
                ],
            )
        )
        lower_prompt = prompt.lower()

        self.assertIn("primary_source_path", prompt)
        self.assertIn("src/ci_policy.py", prompt)
        self.assertIn("source_files", prompt)
        self.assertIn("handle_jit_crash", prompt)
        self.assertIn("do not add new dependencies", lower_prompt)
        self.assertIn("do not edit readme", lower_prompt)
        self.assertIn("do not edit dependency files", lower_prompt)
        self.assertIn("preserve existing public function names", lower_prompt)
        self.assertIn("output exactly one file at primary_source_path", lower_prompt)

    def test_downstream_patch_provider_receives_current_allowed_source_files(self):
        fixture = load_hero_fixture(PROJECT_ODYSSEY_FIXTURE_ROOT)
        provider = CapturingPatchProvider()

        result = run_downstream_proof(
            fixture,
            selected_context=[
                {
                    "source_ref": "session-h-current:turn-006",
                    "text": "Mojo JIT crashes are now real bugs. Do not add retry loops, continue-on-error, or skip markers; fix forward with a minimal reproducer.",
                },
                {
                    "source_ref": "session-h-history:turn-004",
                    "text": "Do not add new dependencies for CI or test-runner fixes.",
                },
            ],
            variant_id="recallpack",
            patch_provider=provider,
        )

        self.assertEqual(result["summary"], {"passed": 3, "failed": 0})
        self.assertEqual(len(provider.requests), 1)
        request = provider.requests[0]
        source_files = {file["path"]: file["content"] for file in request.source_files}
        self.assertIn("src/ci_policy.py", source_files)
        self.assertIn("def handle_jit_crash", source_files["src/ci_policy.py"])
        self.assertIn("pyproject.toml", source_files)
        self.assertEqual(
            result["patch_generation"]["source_file_paths"],
            ["src/ci_policy.py", "pyproject.toml"],
        )

    def test_allowed_source_files_do_not_read_outside_repo_root(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            repo_root = temp_root / "repo"
            (repo_root / "src").mkdir(parents=True)
            (repo_root / "src" / "ci_policy.py").write_text("def policy():\n    return {}\n")
            (temp_root / "secret.txt").write_text("local secret")

            source_files = _allowed_source_files(
                repo_root,
                ["src/ci_policy.py", "../secret.txt"],
            )

        self.assertEqual(
            source_files,
            [{"path": "src/ci_policy.py", "content": "def policy():\n    return {}\n"}],
        )

    def test_downstream_output_validator_rejects_unapproved_or_duplicate_paths(self):
        allowed = ["src/retry.py", "pyproject.toml"]

        ok = validate_downstream_files(
            [{"path": "src/retry.py", "content": "def retry(): pass"}],
            allowed_paths=allowed,
        )
        duplicate = validate_downstream_files(
            [
                {"path": "src/retry.py", "content": "a"},
                {"path": "src/retry.py", "content": "b"},
            ],
            allowed_paths=allowed,
        )
        third_file = validate_downstream_files(
            [{"path": "README.md", "content": "leak"}],
            allowed_paths=allowed,
        )

        self.assertTrue(ok.accepted)
        self.assertFalse(duplicate.accepted)
        self.assertEqual(duplicate.error, "duplicate_path")
        self.assertFalse(third_file.accepted)
        self.assertEqual(third_file.error, "path_not_allowed")

    def test_downstream_validation_rejects_path_traversal_even_if_allowed(self):
        validation = validate_downstream_files(
            files=[{"path": "../secret.txt", "content": "leak"}],
            allowed_paths=["../secret.txt"],
        )

        self.assertFalse(validation.accepted)
        self.assertEqual(validation.error, "path_not_allowed")

    def test_downstream_rejected_patch_preserves_patch_generation_trace(self):
        fixture = load_hero_fixture(FIXTURE_ROOT)
        result = run_downstream_proof(
            fixture,
            selected_context=[],
            variant_id="bad_live_patch",
            patch_provider=UnapprovedPathPatchProvider(),
        )

        self.assertFalse(result["accepted"])
        self.assertEqual(result["error"], "path_not_allowed")
        self.assertEqual(result["summary"], {"passed": 0, "failed": 3})
        self.assertEqual(result["patch_generation"]["provider_role"], "patch_generation")
        self.assertEqual(result["patch_generation"]["request_id"], "unapproved-path")
        self.assertEqual(result["patch_generation"]["output_paths"], ["README.md"])
        self.assertFalse(result["patch_generation"]["used_gold_patch_variants"])

    def test_downstream_output_validator_rejects_unsafe_generated_python(self):
        allowed = ["src/retry.py"]

        dangerous_import = validate_downstream_files(
            [
                {
                    "path": "src/retry.py",
                    "content": "import os\n\n\ndef retry(operation):\n    return os.listdir('/')\n",
                }
            ],
            allowed_paths=allowed,
        )
        dangerous_call = validate_downstream_files(
            [
                {
                    "path": "src/retry.py",
                    "content": "def retry(operation):\n    return open('/etc/passwd').read()\n",
                }
            ],
            allowed_paths=allowed,
        )

        self.assertFalse(dangerous_import.accepted)
        self.assertEqual(dangerous_import.error, "unsafe_python_content")
        self.assertFalse(dangerous_call.accepted)
        self.assertEqual(dangerous_call.error, "unsafe_python_content")

    def test_downstream_proof_records_hidden_test_runtime_errors_as_failures(self):
        fixture = load_hero_fixture(FIXTURE_ROOT)

        proof = run_downstream_proof(
            fixture,
            selected_context=[],
            variant_id="missing_retry",
            patch_provider=MissingRetryPatchProvider(),
        )

        self.assertTrue(proof["accepted"])
        self.assertEqual(proof["summary"], {"passed": 0, "failed": 3})
        self.assertEqual(len(proof["tests"]), 3)
        self.assertTrue(all(not test["passed"] for test in proof["tests"]))
        self.assertIn("AttributeError", proof["tests"][0]["detail"])

    def test_second_fixture_proves_lifecycle_advantage_without_project_a_retry_coupling(self):
        fixture = load_hero_fixture(SECOND_FIXTURE_ROOT)
        result = evaluate_hero_fixture(SECOND_FIXTURE_ROOT)

        self.assertEqual(fixture.gold["project_id"], "project-b")
        self.assertEqual(fixture.gold["component"], "config")
        self.assertNotEqual(fixture.gold["component"], "retry")

        embedding_rag = result.variants["embedding_top_k_rag"]
        recallpack = result.variants["recallpack"]
        baseline_sources = [item["source_ref"] for item in embedding_rag.selected_context]
        recallpack_sources = [item["source_ref"] for item in recallpack.selected_context]

        self.assertIn("session-b:turn-001", baseline_sources)
        self.assertNotIn("session-b:turn-005", baseline_sources)
        self.assertEqual(
            recallpack_sources,
            ["session-b:turn-005", "session-b:turn-003"],
        )
        self.assertEqual(embedding_rag.downstream["summary"], {"passed": 1, "failed": 2})
        self.assertEqual(recallpack.downstream["summary"], {"passed": 3, "failed": 0})
        self.assertIn("return config.get(key)", embedding_rag.downstream["patch_diff"])
        self.assertIn("return None", embedding_rag.downstream["causal_reason"])
        self.assertIn("class ConfigError", recallpack.downstream["patch_diff"])
        self.assertEqual(recallpack.compile_trace["retrieval_mode"], "embedding_top_n")
        self.assertEqual(recallpack.metrics["required_memory_recall_at_budget"], 1.0)
        self.assertEqual(recallpack.metrics["stale_leakage_rate"], 0.0)

    def test_multi_fixture_benchmark_covers_cache_and_serializer_patterns(self):
        cases = [
            {
                "root": THIRD_FIXTURE_ROOT,
                "project_id": "project-c",
                "component": "cache",
                "stale": "session-c:turn-001",
                "current": "session-c:turn-005",
                "preference": "session-c:turn-003",
                "current_patch_signal": "DEFAULT_TTL_SECONDS = 60",
            },
            {
                "root": FOURTH_FIXTURE_ROOT,
                "project_id": "project-d",
                "component": "serializer",
                "stale": "session-d:turn-001",
                "current": "session-d:turn-005",
                "preference": "session-d:turn-003",
                "current_patch_signal": "'[redacted]'",
            },
        ]

        for case in cases:
            with self.subTest(project_id=case["project_id"]):
                fixture = load_hero_fixture(case["root"])
                result = evaluate_hero_fixture(case["root"])

                self.assertEqual(fixture.gold["project_id"], case["project_id"])
                self.assertEqual(fixture.gold["component"], case["component"])

                embedding_rag = result.variants["embedding_top_k_rag"]
                recallpack = result.variants["recallpack"]
                baseline_sources = [
                    item["source_ref"] for item in embedding_rag.selected_context
                ]
                recallpack_sources = [
                    item["source_ref"] for item in recallpack.selected_context
                ]

                self.assertIn(case["stale"], baseline_sources)
                self.assertNotIn(case["current"], baseline_sources)
                self.assertEqual(
                    recallpack_sources,
                    [case["current"], case["preference"]],
                )
                self.assertEqual(
                    embedding_rag.downstream["summary"],
                    {"passed": 0, "failed": 3},
                )
                self.assertFalse(embedding_rag.downstream["accepted"])
                self.assertEqual(embedding_rag.downstream["error"], "empty_patch")
                self.assertEqual(
                    recallpack.downstream["summary"],
                    {"passed": 3, "failed": 0},
                )
                self.assertIn(
                    case["current_patch_signal"],
                    recallpack.downstream["patch_diff"],
                )
                self.assertEqual(
                    recallpack.metrics["required_memory_recall_at_budget"],
                    1.0,
                )
                self.assertEqual(recallpack.metrics["stale_leakage_rate"], 0.0)

    def test_fifth_fixture_is_non_isomorphic_pagination_lifecycle_proof(self):
        fixture = load_hero_fixture(FIFTH_FIXTURE_ROOT)
        result = evaluate_hero_fixture(FIFTH_FIXTURE_ROOT)

        self.assertEqual(fixture.gold["project_id"], "project-e")
        self.assertEqual(fixture.gold["component"], "pagination")
        self.assertEqual(
            fixture.gold["fixture_structure"],
            "non_isomorphic_multi_session_sparse_event_ids",
        )

        embedding_rag = result.variants["embedding_top_k_rag"]
        recallpack = result.variants["recallpack"]
        baseline_sources = [item["source_ref"] for item in embedding_rag.selected_context]
        recallpack_sources = [item["source_ref"] for item in recallpack.selected_context]

        self.assertIn("session-e-alpha:note-002", baseline_sources)
        self.assertNotIn("session-e-gamma:decision-001", baseline_sources)
        self.assertEqual(
            recallpack_sources,
            ["session-e-gamma:decision-001", "session-e-beta:pref-002"],
        )
        self.assertEqual(
            embedding_rag.downstream["summary"],
            {"passed": 0, "failed": 3},
        )
        self.assertFalse(embedding_rag.downstream["accepted"])
        self.assertEqual(embedding_rag.downstream["error"], "empty_patch")
        self.assertEqual(
            recallpack.downstream["summary"],
            {"passed": 3, "failed": 0},
        )
        self.assertIn(
            "cursor",
            recallpack.downstream["patch_diff"],
        )
        self.assertIn(
            "min(limit, 100)",
            recallpack.downstream["patch_diff"],
        )
        self.assertEqual(
            recallpack.metrics["required_memory_recall_at_budget"],
            1.0,
        )
        self.assertEqual(recallpack.metrics["stale_leakage_rate"], 0.0)

    def test_realistic_repo_fixture_uses_real_temp_repo_patch_execution(self):
        fixture = load_hero_fixture(REALISTIC_FIXTURE_ROOT)
        result = evaluate_hero_fixture(REALISTIC_FIXTURE_ROOT)

        provenance = REALISTIC_FIXTURE_ROOT / "provenance.md"
        self.assertTrue(provenance.is_file())
        provenance_text = provenance.read_text().lower()
        self.assertIn("realistic scenario fixture", provenance_text)
        self.assertIn("not a live production trace", provenance_text)
        self.assertIn("inspired by public maintenance patterns", provenance_text)

        self.assertEqual(fixture.gold["project_id"], "project-f-realistic")
        self.assertEqual(fixture.gold["component"], "api_client")
        self.assertEqual(
            fixture.gold["fixture_structure"],
            "realistic_repo_style_multi_session_with_noise",
        )
        self.assertGreaterEqual(len(fixture.events), 14)
        self.assertLessEqual(len(fixture.events), 18)

        embedding_rag = result.variants["embedding_top_k_rag"]
        recallpack = result.variants["recallpack"]
        baseline_sources = [item["source_ref"] for item in embedding_rag.selected_context]
        recallpack_sources = [item["source_ref"] for item in recallpack.selected_context]

        self.assertIn("session-f-setup:turn-002", baseline_sources)
        self.assertNotIn("session-f-fix:turn-006", baseline_sources)
        self.assertEqual(
            recallpack_sources,
            ["session-f-fix:turn-006", "session-f-setup:turn-004"],
        )
        self.assertEqual(
            embedding_rag.downstream["summary"],
            {"passed": 1, "failed": 2},
        )
        self.assertEqual(
            recallpack.downstream["summary"],
            {"passed": 3, "failed": 0},
        )
        self.assertEqual(
            embedding_rag.downstream["execution_mode"],
            "temp_repo_hidden_tests",
        )
        self.assertIn("Authorization", embedding_rag.downstream["patch_diff"])
        self.assertIn("X-Api-Key", recallpack.downstream["patch_diff"])
        self.assertIn("timeout=10", recallpack.downstream["patch_diff"])
        self.assertEqual(
            recallpack.metrics["required_memory_recall_at_budget"],
            1.0,
        )
        self.assertEqual(recallpack.metrics["stale_leakage_rate"], 0.0)

    def test_source_backed_auth_mode_fixture_proves_header_lifecycle(self):
        fixture = load_hero_fixture(AUTH_MODE_FIXTURE_ROOT)
        result = evaluate_hero_fixture(AUTH_MODE_FIXTURE_ROOT)

        provenance = AUTH_MODE_FIXTURE_ROOT / "provenance.md"
        self.assertTrue(provenance.is_file())
        provenance_text = provenance.read_text().lower()
        self.assertIn("source-backed pattern fixture", provenance_text)
        self.assertIn("higress", provenance_text)
        self.assertIn("vscode", provenance_text)
        self.assertIn("not copied", provenance_text)

        self.assertEqual(fixture.gold["project_id"], "project-g-auth-mode")
        self.assertEqual(fixture.gold["component"], "provider_auth")
        self.assertEqual(
            fixture.gold["fixture_structure"],
            "source_backed_ai_provider_auth_header_mode",
        )

        embedding_rag = result.variants["embedding_top_k_rag"]
        recallpack = result.variants["recallpack"]
        baseline_sources = [item["source_ref"] for item in embedding_rag.selected_context]
        recallpack_sources = [item["source_ref"] for item in recallpack.selected_context]

        self.assertIn("session-g-alpha:turn-002", baseline_sources)
        self.assertNotIn("session-g-fix:turn-006", baseline_sources)
        self.assertEqual(
            recallpack_sources,
            ["session-g-alpha:turn-004", "session-g-fix:turn-006"],
        )
        self.assertEqual(
            embedding_rag.downstream["summary"],
            {"passed": 1, "failed": 2},
        )
        self.assertEqual(
            recallpack.downstream["summary"],
            {"passed": 3, "failed": 0},
        )
        self.assertIn(
            'headers["Authorization"] = inbound_headers.get("Authorization", "")',
            embedding_rag.downstream["patch_diff"],
        )
        self.assertIn("X-Api-Key", recallpack.downstream["patch_diff"])
        self.assertIn("headers.pop(\"Authorization\", None)", recallpack.downstream["patch_diff"])
        self.assertIn("Bearer", recallpack.downstream["patch_diff"])
        self.assertEqual(
            recallpack.metrics["required_memory_recall_at_budget"],
            1.0,
        )
        self.assertEqual(recallpack.metrics["stale_leakage_rate"], 0.0)

    def test_projectodyssey_fixture_proves_unrigged_stale_jit_retrieval(self):
        fixture = load_hero_fixture(PROJECT_ODYSSEY_FIXTURE_ROOT)
        result = evaluate_hero_fixture(PROJECT_ODYSSEY_FIXTURE_ROOT)

        provenance = PROJECT_ODYSSEY_FIXTURE_ROOT / "provenance.md"
        self.assertTrue(provenance.is_file())
        provenance_text = provenance.read_text().lower()
        self.assertIn("source-backed scenario", provenance_text)
        self.assertIn("not a production trace", provenance_text)
        self.assertIn("projectodyssey", provenance_text)
        self.assertIn("47d9ddc", provenance_text)
        self.assertIn("claude.md", provenance_text)

        self.assertEqual(fixture.gold["project_id"], "project-h-projectodyssey-jit")
        self.assertEqual(fixture.gold["component"], "ci_policy")
        self.assertEqual(
            fixture.gold["fixture_structure"],
            "source_backed_projectodyssey_jit_unrigged_retrieval",
        )
        self.assertNotIn("baseline_embedding_terms", fixture.gold)
        self.assertNotIn("baseline_downrank_phrases", fixture.gold)

        embedding_rag = result.variants["embedding_top_k_rag"]
        recallpack = result.variants["recallpack"]
        baseline_sources = [item["source_ref"] for item in embedding_rag.selected_context]
        recallpack_sources = [item["source_ref"] for item in recallpack.selected_context]

        self.assertIn("session-h-history:turn-002", baseline_sources)
        self.assertIn("session-h-current:turn-004", baseline_sources)
        self.assertNotIn("session-h-current:turn-006", baseline_sources)
        self.assertEqual(
            recallpack_sources,
            ["session-h-current:turn-006", "session-h-history:turn-004"],
        )
        self.assertEqual(
            embedding_rag.downstream["summary"],
            {"passed": 1, "failed": 2},
        )
        self.assertEqual(
            recallpack.downstream["summary"],
            {"passed": 3, "failed": 0},
        )
        self.assertIn("retry", embedding_rag.downstream["patch_diff"].lower())
        self.assertIn(
            "minimal_reproducer_required",
            recallpack.downstream["patch_diff"],
        )
        self.assertEqual(
            recallpack.metrics["required_memory_recall_at_budget"],
            1.0,
        )
        self.assertEqual(recallpack.metrics["stale_leakage_rate"], 0.0)

class HeroEvaluationV4ContractTests(unittest.TestCase):
    def _assert_value_error_code(self, fn, *args, code: str, **kwargs):
        with self.assertRaisesRegex(ValueError, code):
            fn(*args, **kwargs)

    def _bind_attempts(self, manifest, attempts):
        manifest_hash = hashlib.sha256(
            canonical_json(manifest).encode("utf-8")
        ).hexdigest()
        for registration_order, attempt in enumerate(attempts):
            attempt["execution_manifest_sha256"] = manifest_hash
            attempt["registration_order"] = registration_order
            attempt["attempt_no"] = registration_order + 1
        return attempts

    def test_v4_comparison_contract_rejects_invalid_mutations_with_stable_codes(self):
        manifest = build_floor_execution_manifest()
        artifact_bytes = build_artifact_bytes(manifest)
        validate = getattr(evaluation_module, "validate_v4_comparison_contract")

        result = validate(manifest, artifact_bytes=artifact_bytes)
        self.assertEqual(result["budget_tokens"], 512)
        self.assertEqual(result["comparable_variants"], V4_VARIANTS[1:])
        self.assertEqual(result["raw_history_variant"], "raw_full_history")
        self.assertEqual(
            result["shared_input_artifact_ids"],
            {
                "repository_snapshot_artifact_id": "repo_snapshot",
                "model_visible_snapshot_artifact_id": "model_visible_snapshot",
                "prompt_template_artifact_id": "prompt_template",
                "patch_provider_contract_artifact_id": "patch_contract",
                "runner_contract_artifact_id": "runner_contract",
            },
        )
        self.assertEqual(result["hidden_test_visibility"], "after_model_output_fixed")
        self.assertEqual(
            result["writable_paths"],
            [
                "src/retry.py",
                "src/retry_policy.py",
                "src/auth.py",
                "src/config_loader.py",
                "pyproject.toml",
            ],
        )

        invalid_budget = copy.deepcopy(manifest)
        invalid_budget["comparison_contract"]["budget_tokens"] = 256
        self._assert_value_error_code(
            validate,
            invalid_budget,
            artifact_bytes=artifact_bytes,
            code="unequal_comparison_contract",
        )

        invalid_writable_paths = copy.deepcopy(manifest)
        invalid_writable_paths["comparison_contract"]["writable_paths"] = ["src/retry.py"]
        self._assert_value_error_code(
            validate,
            invalid_writable_paths,
            artifact_bytes=artifact_bytes,
            code="unequal_comparison_contract",
        )

        invalid_hidden_visibility = copy.deepcopy(manifest)
        invalid_hidden_visibility["comparison_contract"]["hidden_test_visibility"] = (
            "before_model_output_fixed"
        )
        self._assert_value_error_code(
            validate,
            invalid_hidden_visibility,
            artifact_bytes=artifact_bytes,
            code="unequal_comparison_contract",
        )

        invalid_shared_input = copy.deepcopy(manifest)
        invalid_shared_input["comparison_contract"]["model_visible_snapshot_artifact_id"] = (
            "repo_snapshot"
        )
        self._assert_value_error_code(
            validate,
            invalid_shared_input,
            artifact_bytes=artifact_bytes,
            code="invalid_artifact_reference|unequal_comparison_contract",
        )

        invalid_variant_set = copy.deepcopy(manifest)
        invalid_variant_set["variants"] = V4_VARIANTS[:-1]
        self._assert_value_error_code(
            validate,
            invalid_variant_set,
            artifact_bytes=artifact_bytes,
            code="invalid_rung_grid",
        )

        malformed_comparability = copy.deepcopy(manifest)
        malformed_comparability["comparison_contract"]["variant_comparability"][
            "semantic_rerank"
        ] = None
        self._assert_value_error_code(
            validate,
            malformed_comparability,
            artifact_bytes=artifact_bytes,
            code="unequal_comparison_contract",
        )

    def test_v4_designates_first_three_nontechnical_runs_and_rejects_invalid_abort_or_diagnostic_replacement(self):
        manifest = build_floor_execution_manifest()
        designate = getattr(evaluation_module, "designate_v4_claim_runs")
        attempts = self._bind_attempts(
            manifest,
            [
                build_attempt_summary(
                    "eval_technical",
                    "semantic_rerank",
                    full_suite_passed=False,
                    designation="invalidated_technical",
                    failure_code="sandbox_timeout",
                ),
                build_attempt_summary(
                    "eval_1", "semantic_rerank", full_suite_passed=False
                ),
                build_attempt_summary(
                    "eval_2", "semantic_rerank", full_suite_passed=True
                ),
                build_attempt_summary(
                    "eval_3", "semantic_rerank", full_suite_passed=True
                ),
                build_attempt_summary(
                    "eval_diag",
                    "semantic_rerank",
                    full_suite_passed=True,
                    designation="diagnostic",
                ),
                build_attempt_summary(
                    "eval_4", "semantic_rerank", full_suite_passed=True
                ),
            ],
        )

        designation = designate(
            manifest,
            scenario_id="diag-project-a",
            variant_id="semantic_rerank",
            attempts=attempts,
        )
        self.assertEqual(designation["claim_run_ids"], ["eval_1", "eval_2", "eval_3"])
        self.assertEqual(
            designation["retained_run_ids"],
            ["eval_technical", "eval_1", "eval_2", "eval_3", "eval_diag", "eval_4"],
        )
        self.assertEqual(designation["adverse_run_ids"], ["eval_1"])
        self.assertEqual(designation["technical_attempt_ids"], ["eval_technical"])
        self.assertEqual(
            designation["technical_replacements"],
            [{"invalidated_run_id": "eval_technical", "replacement_run_id": "eval_1"}],
        )
        self.assertEqual(designation["ignored_diagnostic_run_ids"], ["eval_diag"])
        self.assertEqual(designation["ignored_extra_run_ids"], ["eval_4"])

        invalid_abort = copy.deepcopy(attempts)
        invalid_abort.insert(
            3,
            build_attempt_summary(
                "eval_abort",
                "semantic_rerank",
                full_suite_passed=False,
                designation="invalidated_abort",
                failure_code="manual_abort",
            ),
        )
        self._bind_attempts(manifest, invalid_abort)
        self._assert_value_error_code(
            designate,
            manifest,
            scenario_id="diag-project-a",
            variant_id="semantic_rerank",
            attempts=invalid_abort,
            code="invalid_designation|invalid_replacement",
        )

        invalid_diagnostic = attempts[:3] + [attempts[4]]
        self._assert_value_error_code(
            designate,
            manifest,
            scenario_id="diag-project-a",
            variant_id="semantic_rerank",
            attempts=invalid_diagnostic,
            code="invalid_replacement",
        )

        forged_hash = copy.deepcopy(attempts)
        for attempt in forged_hash:
            attempt["execution_manifest_sha256"] = "9" * 64
        self._assert_value_error_code(
            designate,
            manifest,
            scenario_id="diag-project-a",
            variant_id="semantic_rerank",
            attempts=forged_hash,
            code="invalid_designation",
        )

        nontechnical_failure = copy.deepcopy(attempts)
        nontechnical_failure[0]["failure"]["code"] = "hidden_tests_failed"
        self._assert_value_error_code(
            designate,
            manifest,
            scenario_id="diag-project-a",
            variant_id="semantic_rerank",
            attempts=nontechnical_failure,
            code="invalid_replacement",
        )

        malformed_taxonomy = copy.deepcopy(manifest)
        malformed_taxonomy["technical_failure_codes"] = None
        self._assert_value_error_code(
            designate,
            malformed_taxonomy,
            scenario_id="diag-project-a",
            variant_id="semantic_rerank",
            attempts=self._bind_attempts(malformed_taxonomy, copy.deepcopy(attempts)),
            code="invalid_designation",
        )

        reordered = copy.deepcopy(attempts)
        reordered[0], reordered[1] = reordered[1], reordered[0]
        self._assert_value_error_code(
            designate,
            manifest,
            scenario_id="diag-project-a",
            variant_id="semantic_rerank",
            attempts=reordered,
            code="invalid_designation",
        )

        self._assert_value_error_code(
            designate,
            manifest,
            scenario_id="diag-project-a",
            variant_id="semantic_rerank",
            attempts=[None],
            code="invalid_designation",
        )

    def test_v4_recomputes_strongest_baseline_and_rejects_invalid_aggregate_inputs(self):
        manifest = build_floor_execution_manifest()
        recompute = getattr(evaluation_module, "recompute_v4_aggregate_metrics")
        runs = self._bind_attempts(manifest, [
            build_attempt_summary(
                "eval_raw_1", "raw_full_history", full_suite_passed=True
            ),
            build_attempt_summary(
                "eval_raw_2", "raw_full_history", full_suite_passed=True
            ),
            build_attempt_summary(
                "eval_raw_3", "raw_full_history", full_suite_passed=True
            ),
            build_attempt_summary("eval_sem_1", "semantic_rerank", full_suite_passed=True),
            build_attempt_summary("eval_sem_2", "semantic_rerank", full_suite_passed=True),
            build_attempt_summary("eval_sem_3", "semantic_rerank", full_suite_passed=False),
            build_attempt_summary("eval_recent_1", "recency_aware", full_suite_passed=True),
            build_attempt_summary("eval_recent_2", "recency_aware", full_suite_passed=False),
            build_attempt_summary("eval_recent_3", "recency_aware", full_suite_passed=False),
            build_attempt_summary(
                "eval_resolver_1",
                "recall_time_resolver",
                full_suite_passed=True,
            ),
            build_attempt_summary(
                "eval_resolver_2",
                "recall_time_resolver",
                full_suite_passed=False,
            ),
            build_attempt_summary(
                "eval_resolver_3",
                "recall_time_resolver",
                full_suite_passed=False,
            ),
            build_attempt_summary("eval_rp_1", "recallpack", full_suite_passed=True),
            build_attempt_summary("eval_rp_2", "recallpack", full_suite_passed=True),
            build_attempt_summary("eval_rp_3", "recallpack", full_suite_passed=False),
        ])
        result = recompute(
            manifest,
            scenario_id="diag-project-a",
            runs=runs,
            reported_run_ids=[run["run_id"] for run in runs],
            reported_adverse_run_ids=[
                run["run_id"]
                for run in runs
                if not run["test_result"]["full_suite_passed"]
            ],
            reported_summary={
                "numerator": 0,
                "denominator": 1,
                "rate": 0.0,
            },
        )
        self.assertTrue(result["raw_history_excluded"])
        self.assertEqual(result["strongest_baseline_variant_id"], "semantic_rerank")
        self.assertEqual(result["strongest_baseline_pass_count"], 2)
        self.assertEqual(result["recallpack_pass_count"], 2)
        self.assertEqual(result["classification"], "tie_neutral")
        self.assertEqual(result["numerator"], 0)
        self.assertEqual(result["denominator"], 1)
        self.assertEqual(result["rate"], 0.0)

        duplicate_reported_runs = [run["run_id"] for run in runs] + ["eval_rp_3"]
        self._assert_value_error_code(
            recompute,
            manifest,
            scenario_id="diag-project-a",
            runs=runs,
            reported_run_ids=duplicate_reported_runs,
            reported_adverse_run_ids=[
                run["run_id"]
                for run in runs
                if not run["test_result"]["full_suite_passed"]
            ],
            reported_summary={
                "numerator": 0,
                "denominator": 1,
                "rate": 0.0,
            },
            code="invalid_aggregate",
        )

        unhashable_run_id = copy.deepcopy(runs)
        unhashable_run_id[0]["run_id"] = []
        self._assert_value_error_code(
            recompute,
            manifest,
            scenario_id="diag-project-a",
            runs=unhashable_run_id,
            reported_run_ids=[],
            reported_adverse_run_ids=[],
            reported_summary={},
            code="invalid_aggregate",
        )

        unhashable_variant = copy.deepcopy(runs)
        unhashable_variant[0]["variant_id"] = []
        self._assert_value_error_code(
            recompute,
            manifest,
            scenario_id="diag-project-a",
            runs=unhashable_variant,
            reported_run_ids=[run["run_id"] for run in unhashable_variant],
            reported_adverse_run_ids=[],
            reported_summary={},
            code="invalid_aggregate",
        )

        self._assert_value_error_code(
            recompute,
            manifest,
            scenario_id="diag-project-a",
            runs=runs,
            reported_run_ids=[[]],
            reported_adverse_run_ids=[],
            reported_summary={},
            code="invalid_aggregate",
        )

        self._assert_value_error_code(
            recompute,
            manifest,
            scenario_id="diag-project-a",
            runs=runs,
            reported_run_ids=[run["run_id"] for run in runs],
            reported_adverse_run_ids=[],
            reported_summary=None,
            code="invalid_aggregate",
        )

        omitted_adverse_runs = [
            run["run_id"]
            for run in runs
            if not run["test_result"]["full_suite_passed"] and run["run_id"] != "eval_recent_2"
        ]
        self._assert_value_error_code(
            recompute,
            manifest,
            scenario_id="diag-project-a",
            runs=runs,
            reported_run_ids=[run["run_id"] for run in runs],
            reported_adverse_run_ids=omitted_adverse_runs,
            reported_summary={
                "numerator": 0,
                "denominator": 1,
                "rate": 0.0,
            },
            code="invalid_aggregate",
        )

        cross_manifest_runs = copy.deepcopy(runs)
        cross_manifest_runs[-1]["execution_manifest_sha256"] = "9" * 64
        self._assert_value_error_code(
            recompute,
            manifest,
            scenario_id="diag-project-a",
            runs=cross_manifest_runs,
            reported_run_ids=[run["run_id"] for run in cross_manifest_runs],
            reported_adverse_run_ids=[
                run["run_id"]
                for run in cross_manifest_runs
                if not run["test_result"]["full_suite_passed"]
            ],
            reported_summary={
                "numerator": 0,
                "denominator": 1,
                "rate": 0.0,
            },
            code="invalid_aggregate",
        )

        wrong_summary = {"numerator": 1, "denominator": 1, "rate": 1.0}
        self._assert_value_error_code(
            recompute,
            manifest,
            scenario_id="diag-project-a",
            runs=runs,
            reported_run_ids=[run["run_id"] for run in runs],
            reported_adverse_run_ids=[
                run["run_id"]
                for run in runs
                if not run["test_result"]["full_suite_passed"]
            ],
            reported_summary=wrong_summary,
            code="invalid_aggregate",
        )

        missing_raw_history = [
            run for run in runs if run["variant_id"] != "raw_full_history"
        ]
        self._assert_value_error_code(
            recompute,
            manifest,
            scenario_id="diag-project-a",
            runs=missing_raw_history,
            reported_run_ids=[run["run_id"] for run in missing_raw_history],
            reported_adverse_run_ids=[
                run["run_id"]
                for run in missing_raw_history
                if not run["test_result"]["full_suite_passed"]
            ],
            reported_summary={"numerator": 0, "denominator": 1, "rate": 0.0},
            code="invalid_aggregate",
        )

        contradictory_outcome = copy.deepcopy(runs)
        failed = next(
            run
            for run in contradictory_outcome
            if not run["test_result"]["full_suite_passed"]
        )
        failed["outcome"] = {
            "status": "completed",
            "stage": "complete",
            "code": "success",
        }
        self._assert_value_error_code(
            recompute,
            manifest,
            scenario_id="diag-project-a",
            runs=contradictory_outcome,
            reported_run_ids=[run["run_id"] for run in contradictory_outcome],
            reported_adverse_run_ids=[
                run["run_id"]
                for run in contradictory_outcome
                if run["outcome"]["status"] == "adverse"
            ],
            reported_summary={"numerator": 0, "denominator": 1, "rate": 0.0},
            code="invalid_run_outcome|invalid_aggregate",
        )

        self._assert_value_error_code(
            recompute,
            manifest,
            scenario_id="diag-project-a",
            runs=[None],
            reported_run_ids=[],
            reported_adverse_run_ids=[],
            reported_summary={},
            code="invalid_aggregate",
        )

    def test_v4_floor_diagnostic_execution_produces_structural_only_hash_linked_packet(self):
        manifest = build_floor_execution_manifest()
        artifact_bytes = build_artifact_bytes(manifest)
        fake_runner_outputs = build_floor_runner_payloads(manifest)
        runner = getattr(evaluation_module, "run_v4_floor_diagnostic")

        packet = runner(
            manifest=manifest,
            isolated_runner=fake_runner_outputs,
            artifact_bytes=artifact_bytes,
        )
        self.assertEqual(packet["record_type"], "floor_diagnostic_preview")
        self.assertFalse(packet["evidence_artifacts_emitted"])
        self.assertEqual(
            [run["variant_id"] for run in packet["runs"]],
            V4_VARIANTS,
        )
        self.assertEqual(packet["retained_run_ids"], [run["run_id"] for run in packet["runs"]])
        self.assertTrue(all(run["designation"] == "diagnostic" for run in packet["runs"]))
        self.assertTrue(all(not run["provider_mode_live"] for run in packet["runs"]))
        for run in packet["runs"]:
            expected = fake_runner_outputs[run["variant_id"]]
            self.assertEqual(run["context_evidence"]["sha256"], expected["context_sha256"])
            self.assertEqual(run["context_artifact_bytes"], expected["context_bytes"])
            self.assertEqual(
                run["context_evidence"]["exact_token_count"],
                expected["exact_token_count"],
            )
        self.assertEqual(packet["summary"]["n"], 5)
        self.assertEqual(packet["summary"]["numerator"], 3)
        self.assertEqual(packet["summary"]["denominator"], 5)
        self.assertEqual(packet["summary"]["rate"], 0.6)
        self.assertEqual(
            [claim["claim_id"] for claim in packet["claims"]],
            [claim["claim_id"] for claim in manifest["claim_declarations"]],
        )
        self.assertEqual(len(packet["claims"]), 1)
        self.assertEqual(
            packet["claims"][0]["claim_type"],
            "structural_runtime",
        )
        self.assertEqual(packet["claims"][0]["status"], "disabled")
        self.assertEqual(packet["claims"][0]["decision_reason"], "evidence_incomplete")
        self.assertNotIn(
            "downstream_superiority",
            json.dumps(packet),
        )
        self.assertNotIn("partial_evidence_manifest", packet)
        self.assertNotIn("final_evidence_manifest", packet)
        self.assertNotIn("aggregates", packet)

        over_budget = copy.deepcopy(fake_runner_outputs)
        over_budget["semantic_rerank"]["exact_token_count"] = 513
        self._assert_value_error_code(
            runner,
            manifest=manifest,
            isolated_runner=over_budget,
            artifact_bytes=artifact_bytes,
            code="unequal_comparison_contract",
        )

        duplicate_run_ids = copy.deepcopy(fake_runner_outputs)
        for output in duplicate_run_ids.values():
            output["run_id"] = "eval_duplicate"
        self._assert_value_error_code(
            runner,
            manifest=manifest,
            isolated_runner=duplicate_run_ids,
            artifact_bytes=artifact_bytes,
            code="invalid_designation",
        )

        empty_grid = copy.deepcopy(manifest)
        empty_grid["execution_order"] = []
        self._assert_value_error_code(
            runner,
            manifest=empty_grid,
            isolated_runner={},
            artifact_bytes=artifact_bytes,
            code="invalid_rung_grid",
        )

        malformed_slot = copy.deepcopy(manifest)
        malformed_slot["execution_order"][0] = None
        self._assert_value_error_code(
            runner,
            manifest=malformed_slot,
            isolated_runner=fake_runner_outputs,
            artifact_bytes=artifact_bytes,
            code="invalid_rung_grid",
        )

        missing_scenario = copy.deepcopy(manifest)
        del missing_scenario["execution_order"][0]["scenario_slot"]
        self._assert_value_error_code(
            runner,
            manifest=missing_scenario,
            isolated_runner=fake_runner_outputs,
            artifact_bytes=artifact_bytes,
            code="invalid_rung_grid",
        )

        malformed_claim = copy.deepcopy(manifest)
        malformed_claim["claim_declarations"] = [None]
        self._assert_value_error_code(
            runner,
            manifest=malformed_claim,
            isolated_runner=fake_runner_outputs,
            artifact_bytes=artifact_bytes,
            code="invalid_claim_reference",
        )

        missing_claim_fields = copy.deepcopy(manifest)
        missing_claim_fields["claim_declarations"] = [{}]
        self._assert_value_error_code(
            runner,
            manifest=missing_claim_fields,
            isolated_runner=fake_runner_outputs,
            artifact_bytes=artifact_bytes,
            code="invalid_claim_reference",
        )

        malformed_limitations = copy.deepcopy(manifest)
        malformed_limitations["claim_declarations"][0]["limitations"] = None
        self._assert_value_error_code(
            runner,
            manifest=malformed_limitations,
            isolated_runner=fake_runner_outputs,
            artifact_bytes=artifact_bytes,
            code="invalid_claim_reference",
        )

    def test_v4_floor_evidence_pipeline_emits_schema_valid_structural_only_partial_evidence(self):
        source_ledger = build_source_ledger("diag-project-a")
        relation_ledger = build_relation_label_ledger(
            "diag-project-a",
            source_ledger,
            entries=[],
        )
        source_ledgers = {"diag-project-a": source_ledger}
        relation_ledgers = {"diag-project-a": relation_ledger}
        manifest = build_floor_execution_manifest(
            source_ledgers=source_ledgers,
            relation_label_ledgers=relation_ledgers,
        )
        frozen_manifest = copy.deepcopy(manifest)
        self.assertTrue(
            hasattr(evaluation_module, "run_v4_floor_evidence_pipeline"),
            "formal V4 Floor evidence pipeline is not implemented",
        )
        packet = evaluation_module.run_v4_floor_evidence_pipeline(
            manifest=manifest,
            finalized_runner_output_loader=build_floor_runner_output_loader(manifest),
            input_artifact_bytes=build_artifact_bytes(
                manifest,
                source_ledgers=source_ledgers,
            ),
            source_ledgers=source_ledgers,
            relation_label_ledgers=relation_ledgers,
        )

        self.assertEqual(manifest, frozen_manifest)
        self.assertEqual(packet["record_type"], "v4_floor_evidence_packet")
        self.assertEqual(
            packet["test_only_simulation_marker"],
            "TEST_ONLY_FAKE_RUNNER_OUTPUTS_NOT_PUBLIC_EVIDENCE",
        )
        self.assertTrue(packet["evidence_artifacts_emitted"])
        self.assertEqual(len(packet["runs"]), len(V4_VARIANTS))
        self.assertEqual(
            [run["variant_id"] for run in packet["runs"]],
            V4_VARIANTS,
        )
        self.assertTrue(
            all(run["designation"] == "diagnostic" for run in packet["runs"])
        )
        self.assertTrue(
            all(not run["provider_traces"][0]["live"] for run in packet["runs"])
        )
        self.assertEqual(
            [],
            [
                error
                for run in packet["runs"]
                for error in definition_validator("run").iter_errors(run)
            ],
        )
        self.assertEqual(
            [],
            list(
                definition_validator("aggregate").iter_errors(
                    packet["aggregate_report"]
                )
            ),
        )

        self.assertEqual(
            [],
            list(
                definition_validator("evidenceManifest").iter_errors(
                    packet["evidence_manifest"]
                )
            ),
        )

        validate_execution_manifest(
            manifest,
            artifact_bytes=packet["artifact_bytes"],
            source_ledgers=source_ledgers,
        )
        for run in packet["runs"]:
            validate_evaluation_run(
                run,
                manifest,
                artifact_bytes=packet["artifact_bytes"],
                source_ledger=source_ledger,
                relation_label_ledger=relation_ledger,
            )
        validate_aggregate_report(
            packet["aggregate_report"],
            execution_manifest=manifest,
            retained_attempt_loader=packet["retained_attempt_loader"],
            artifact_bytes=packet["artifact_bytes"],
            source_ledgers=source_ledgers,
            relation_label_ledgers=relation_ledgers,
        )
        validate_evidence_manifest(
            packet["evidence_manifest"],
            manifest,
            retained_attempt_loader=packet["retained_attempt_loader"],
            artifact_bytes=packet["artifact_bytes"],
            source_ledgers=source_ledgers,
            relation_label_ledgers=relation_ledgers,
        )

        aggregate = packet["aggregate_report"]
        self.assertEqual(aggregate["claim_type"], "structural_runtime")
        self.assertEqual(
            aggregate["run_ids"],
            [run["run_id"] for run in packet["runs"]],
        )
        self.assertEqual(
            aggregate["adverse_run_ids"],
            [
                run["run_id"]
                for run in packet["runs"]
                if run["outcome"]["status"] == "adverse"
            ],
        )
        self.assertEqual(
            aggregate["metrics"],
            [
                {
                    "metric_id": "runtime_contract_success",
                    "n": len(V4_VARIANTS),
                    "numerator": len(V4_VARIANTS),
                    "denominator": len(V4_VARIANTS),
                    "rate": 1.0,
                }
            ],
        )

        evidence = packet["evidence_manifest"]
        self.assertEqual(evidence["status"], "partial")
        self.assertEqual(
            evidence["run_ids"],
            [run["run_id"] for run in packet["runs"]],
        )
        self.assertEqual(evidence["aggregate_ids"], [])
        self.assertEqual(len(evidence["claims"]), 1)
        self.assertEqual(evidence["claims"][0]["claim_type"], "structural_runtime")
        self.assertEqual(evidence["claims"][0]["status"], "disabled")
        self.assertEqual(
            evidence["claims"][0]["decision_reason"],
            "evidence_incomplete",
        )
        self.assertNotIn("downstream_superiority", json.dumps(packet, default=str))

    def test_v4_floor_production_journal_emits_final_evidence(self):
        source_ledger = build_source_ledger("diag-project-a")
        relation_ledger = build_relation_label_ledger(
            "diag-project-a", source_ledger, entries=[]
        )
        source_ledgers = {"diag-project-a": source_ledger}
        relation_ledgers = {"diag-project-a": relation_ledger}
        manifest = build_floor_execution_manifest(
            source_ledgers=source_ledgers,
            relation_label_ledgers=relation_ledgers,
        )
        manifest_sha256 = canonical_sha256(manifest)
        journal_type = getattr(
            evaluation_module,
            "ProductionRunnerOutputJournal",
            None,
        )
        self.assertIsNotNone(
            journal_type,
            "production evidence requires an evaluator-owned append-only journal",
        )
        journal = journal_type(manifest_sha256)
        payloads = build_floor_runner_payloads(manifest)
        for slot in manifest["execution_order"]:
            variant_id = slot["variant_id"]
            output = payloads[variant_id]
            isolated_result, expected_identity = _receipted_floor_output(
                manifest,
                slot,
                output,
            )
            journal.append(
                scenario_id=slot["scenario_slot"],
                slot_index=slot["slot_index"],
                variant_id=variant_id,
                attempt_no=slot["repetition"],
                output=output,
                isolated_result=isolated_result,
                expected_identity=expected_identity,
            )
        finalized_authority = journal.finalize()

        with self.assertRaisesRegex(RuntimeError, "journal is finalized"):
            journal.append(
                scenario_id="diag-project-a",
                slot_index=99,
                variant_id="raw_full_history",
                attempt_no=1,
                output=payloads["raw_full_history"],
            )

        packet = evaluation_module.run_v4_floor_evidence_pipeline(
            manifest=manifest,
            finalized_runner_output_loader=finalized_authority,
            input_artifact_bytes=build_artifact_bytes(
                manifest,
                source_ledgers=source_ledgers,
            ),
            source_ledgers=source_ledgers,
            relation_label_ledgers=relation_ledgers,
        )

        self.assertNotIn("test_only_simulation_marker", packet)
        self.assertEqual(packet["evidence_status"], "final_production_evidence")
        self.assertEqual(packet["evidence_manifest"]["status"], "final")
        self.assertEqual(packet["evidence_manifest"]["claims"][0]["status"], "enabled")
        self.assertEqual(
            packet["runner_authority_kind"],
            "production_finalized_runner_output_authority",
        )
        retained = packet["retained_attempt_loader"].load_finalized_population(
            manifest_sha256
        )
        self.assertEqual(
            retained["authority_kind"],
            "production_append_only_attempt_journal",
        )

    def test_v4_production_journal_rejects_binding_without_frozen_source_digests(self):
        source_ledger = build_source_ledger("diag-project-a")
        relation_ledger = build_relation_label_ledger(
            "diag-project-a", source_ledger, entries=[]
        )
        manifest = build_floor_execution_manifest(
            source_ledgers={"diag-project-a": source_ledger},
            relation_label_ledgers={"diag-project-a": relation_ledger},
        )
        manifest_sha256 = canonical_sha256(manifest)
        slot = manifest["execution_order"][0]
        output = build_floor_runner_payloads(manifest)[slot["variant_id"]]
        output["runtime_trace"]["execution_binding"] = {
            "variant_id": slot["variant_id"],
            "authority_mode": "production_docker",
            "execution_manifest_sha256": manifest_sha256,
            "scenario_id": slot["scenario_slot"],
            "slot_index": slot["slot_index"],
            "attempt_no": slot["repetition"],
        }
        journal = evaluation_module.ProductionRunnerOutputJournal(manifest_sha256)

        with self.assertRaisesRegex(ValueError, "frozen source digests"):
            journal.append(
                scenario_id=slot["scenario_slot"],
                slot_index=slot["slot_index"],
                variant_id=slot["variant_id"],
                attempt_no=slot["repetition"],
                output=output,
            )

    def test_v4_production_journal_rejects_unreceipted_success_envelope(self):
        source_ledger = build_source_ledger("diag-project-a")
        relation_ledger = build_relation_label_ledger(
            "diag-project-a", source_ledger, entries=[]
        )
        manifest = build_floor_execution_manifest(
            source_ledgers={"diag-project-a": source_ledger},
            relation_label_ledgers={"diag-project-a": relation_ledger},
        )
        manifest_sha256 = canonical_sha256(manifest)
        slot = manifest["execution_order"][0]
        output = build_floor_runner_payloads(manifest)[slot["variant_id"]]
        output["runtime_trace"]["execution_binding"] = {
            "variant_id": slot["variant_id"],
            "authority_mode": "production_docker",
            "execution_manifest_sha256": manifest_sha256,
            "scenario_id": slot["scenario_slot"],
            "slot_index": slot["slot_index"],
            "attempt_no": slot["repetition"],
            "repository_snapshot_sha256": "b" * 64,
            "frozen_hidden_test_tree_sha256": "c" * 64,
        }
        journal = evaluation_module.ProductionRunnerOutputJournal(manifest_sha256)

        with self.assertRaisesRegex(ValueError, "authenticated execution receipt"):
            journal.append(
                scenario_id=slot["scenario_slot"],
                slot_index=slot["slot_index"],
                variant_id=slot["variant_id"],
                attempt_no=slot["repetition"],
                output=output,
            )

    def test_v4_production_journal_rejects_output_tampered_after_receipt(self):
        source_ledger = build_source_ledger("diag-project-a")
        relation_ledger = build_relation_label_ledger(
            "diag-project-a", source_ledger, entries=[]
        )
        manifest = build_floor_execution_manifest(
            source_ledgers={"diag-project-a": source_ledger},
            relation_label_ledgers={"diag-project-a": relation_ledger},
        )
        manifest_sha256 = canonical_sha256(manifest)
        slot = manifest["execution_order"][0]
        output = build_floor_runner_payloads(manifest)[slot["variant_id"]]
        isolated_result, expected_identity = _receipted_floor_output(
            manifest,
            slot,
            output,
        )
        output["patched_files"][0]["content"] += "\n# forged after execution\n"
        journal = evaluation_module.ProductionRunnerOutputJournal(manifest_sha256)

        with self.assertRaisesRegex(ValueError, "does not match its execution receipt"):
            journal.append(
                scenario_id=slot["scenario_slot"],
                slot_index=slot["slot_index"],
                variant_id=slot["variant_id"],
                attempt_no=slot["repetition"],
                output=output,
                isolated_result=isolated_result,
                expected_identity=expected_identity,
            )

    def test_v4_production_journal_rejects_cross_variant_receipt_relabel(self):
        source_ledger = build_source_ledger("diag-project-a")
        relation_ledger = build_relation_label_ledger(
            "diag-project-a", source_ledger, entries=[]
        )
        manifest = build_floor_execution_manifest(
            source_ledgers={"diag-project-a": source_ledger},
            relation_label_ledgers={"diag-project-a": relation_ledger},
        )
        manifest_sha256 = canonical_sha256(manifest)
        slot = manifest["execution_order"][0]
        output = build_floor_runner_payloads(manifest)[slot["variant_id"]]
        isolated_result, expected_identity = _receipted_floor_output(
            manifest,
            slot,
            output,
        )
        relabeled_variant = manifest["execution_order"][1]["variant_id"]
        output["variant_id"] = relabeled_variant
        journal = evaluation_module.ProductionRunnerOutputJournal(manifest_sha256)

        with self.assertRaisesRegex(ValueError, "matching production execution binding"):
            journal.append(
                scenario_id=slot["scenario_slot"],
                slot_index=slot["slot_index"],
                variant_id=relabeled_variant,
                attempt_no=slot["repetition"],
                output=output,
                isolated_result=isolated_result,
                expected_identity=expected_identity,
            )

    def test_v4_production_journal_rejects_tampered_technical_failure_metadata(self):
        source_ledger = build_source_ledger("diag-project-a")
        relation_ledger = build_relation_label_ledger(
            "diag-project-a", source_ledger, entries=[]
        )
        manifest = build_floor_execution_manifest(
            source_ledgers={"diag-project-a": source_ledger},
            relation_label_ledgers={"diag-project-a": relation_ledger},
        )
        manifest_sha256 = canonical_sha256(manifest)
        slot = manifest["execution_order"][0]
        output = build_floor_runner_payloads(manifest)[slot["variant_id"]]
        isolated_result, expected_identity = _receipted_floor_technical_failure(
            manifest,
            slot,
            output,
        )
        output["failure"]["code"] = "sandbox_timeout"
        journal = evaluation_module.ProductionRunnerOutputJournal(manifest_sha256)

        with self.assertRaisesRegex(ValueError, "contradicts its receipt"):
            journal.append(
                scenario_id=slot["scenario_slot"],
                slot_index=slot["slot_index"],
                variant_id=slot["variant_id"],
                attempt_no=slot["repetition"],
                output=output,
                isolated_result=isolated_result,
                expected_identity=expected_identity,
            )

    def test_v4_floor_caller_outputs_cannot_create_production_authority(self):
        source_ledger = build_source_ledger("diag-project-a")
        relation_ledger = build_relation_label_ledger(
            "diag-project-a",
            source_ledger,
            entries=[],
        )
        source_ledgers = {"diag-project-a": source_ledger}
        relation_ledgers = {"diag-project-a": relation_ledger}
        manifest = build_floor_execution_manifest(
            source_ledgers=source_ledgers,
            relation_label_ledgers=relation_ledgers,
        )
        self.assertFalse(
            hasattr(
                evaluation_module,
                "build_evaluator_finalized_runner_output_authority",
            )
        )
        packet = evaluation_module.run_v4_floor_evidence_pipeline(
            manifest=manifest,
            finalized_runner_output_loader=build_floor_runner_output_loader(manifest),
            input_artifact_bytes=build_artifact_bytes(
                manifest,
                source_ledgers=source_ledgers,
            ),
            source_ledgers=source_ledgers,
            relation_label_ledgers=relation_ledgers,
        )

        self.assertEqual(packet["evidence_manifest"]["status"], "partial")
        self.assertEqual(packet["evidence_manifest"]["claims"][0]["status"], "disabled")

    def test_v4_floor_test_authorities_do_not_expose_mutable_internal_snapshots(self):
        source_ledger = build_source_ledger("diag-project-a")
        relation_ledger = build_relation_label_ledger(
            "diag-project-a", source_ledger, entries=[]
        )
        manifest = build_floor_execution_manifest(
            source_ledgers={"diag-project-a": source_ledger},
            relation_label_ledgers={"diag-project-a": relation_ledger},
        )
        runner_loader = build_floor_runner_output_loader(manifest)
        packet = evaluation_module.run_v4_floor_evidence_pipeline(
            manifest=manifest,
            finalized_runner_output_loader=runner_loader,
            input_artifact_bytes=build_artifact_bytes(
                manifest,
                source_ledgers={"diag-project-a": source_ledger},
            ),
            source_ledgers={"diag-project-a": source_ledger},
            relation_label_ledgers={"diag-project-a": relation_ledger},
        )

        self.assertFalse(hasattr(runner_loader, "_snapshot"))
        self.assertFalse(
            hasattr(packet["retained_attempt_loader"], "_authority_snapshot")
        )

    def test_v4_floor_formal_pipeline_rejects_raw_runner_mapping(self):
        source_ledger = build_source_ledger("diag-project-a")
        relation_ledger = build_relation_label_ledger(
            "diag-project-a", source_ledger, entries=[]
        )
        manifest = build_floor_execution_manifest(
            source_ledgers={"diag-project-a": source_ledger},
            relation_label_ledgers={"diag-project-a": relation_ledger},
        )
        with self.assertRaisesRegex(ValueError, "invalid_retained_population"):
            evaluation_module.run_v4_floor_evidence_pipeline(
                manifest=manifest,
                finalized_runner_output_loader=build_floor_runner_payloads(manifest),
                input_artifact_bytes=build_artifact_bytes(
                    manifest,
                    source_ledgers={"diag-project-a": source_ledger},
                ),
                source_ledgers={"diag-project-a": source_ledger},
                relation_label_ledgers={"diag-project-a": relation_ledger},
            )

    def test_v4_floor_formal_pipeline_rejects_noncanonical_claim_prose(self):
        source_ledger = build_source_ledger("diag-project-a")
        relation_ledger = build_relation_label_ledger(
            "diag-project-a", source_ledger, entries=[]
        )
        manifest = build_floor_execution_manifest(
            source_ledgers={"diag-project-a": source_ledger},
            relation_label_ledgers={"diag-project-a": relation_ledger},
        )
        manifest["claim_declarations"][0]["statement"] = (
            "Live qwen_cloud RecallPack beats every downstream baseline."
        )
        with self.assertRaisesRegex(ValueError, "invalid_claim_reference"):
            evaluation_module.run_v4_floor_evidence_pipeline(
                manifest=manifest,
                finalized_runner_output_loader=build_floor_runner_output_loader(manifest),
                input_artifact_bytes=build_artifact_bytes(
                    manifest,
                    source_ledgers={"diag-project-a": source_ledger},
                ),
                source_ledgers={"diag-project-a": source_ledger},
                relation_label_ledgers={"diag-project-a": relation_ledger},
            )

    def test_v4_floor_formal_pipeline_rejects_empty_or_out_of_allowlist_patch(self):
        source_ledger = build_source_ledger("diag-project-a")
        relation_ledger = build_relation_label_ledger(
            "diag-project-a", source_ledger, entries=[]
        )
        manifest = build_floor_execution_manifest(
            source_ledgers={"diag-project-a": source_ledger},
            relation_label_ledgers={"diag-project-a": relation_ledger},
        )
        payloads = build_floor_runner_payloads(manifest)
        payloads["raw_full_history"]["patch_diff"] = ""
        payloads["raw_full_history"]["patched_files"] = [
            {"path": "outside/not-allowed.py", "content": "unsafe = True\n"}
        ]
        with self.assertRaisesRegex(ValueError, "invalid_patch_result"):
            evaluation_module.run_v4_floor_evidence_pipeline(
                manifest=manifest,
                finalized_runner_output_loader=build_floor_runner_output_loader(
                    manifest,
                    payloads=payloads,
                ),
                input_artifact_bytes=build_artifact_bytes(
                    manifest,
                    source_ledgers={"diag-project-a": source_ledger},
                ),
                source_ledgers={"diag-project-a": source_ledger},
                relation_label_ledgers={"diag-project-a": relation_ledger},
            )

    def test_v4_floor_retains_empty_patch_and_sandbox_timeout_attempts(self):
        source_ledger = build_source_ledger("diag-project-a")
        relation_ledger = build_relation_label_ledger(
            "diag-project-a", source_ledger, entries=[]
        )
        source_ledgers = {"diag-project-a": source_ledger}
        relation_ledgers = {"diag-project-a": relation_ledger}
        manifest = build_floor_execution_manifest(
            source_ledgers=source_ledgers,
            relation_label_ledgers=relation_ledgers,
        )
        payloads = build_floor_runner_payloads(manifest)

        empty_patch = payloads["semantic_rerank"]
        empty_patch.update(
            {
                "full_suite_passed": None,
                "patch_diff": "",
                "original_files": [],
                "patched_files": [],
                "test_result": None,
                "attempt_outcome": {
                    "status": "adverse",
                    "stage": "patch_generation",
                    "code": "empty_patch",
                },
            }
        )
        timeout = payloads["raw_full_history"]
        timeout.update(
            {
                "full_suite_passed": None,
                "test_result": None,
                "attempt_outcome": {
                    "status": "invalidated",
                    "stage": "sandbox",
                    "code": "technical_failure",
                },
                "failure": {
                    "code": "sandbox_timeout",
                    "detail": "isolated evaluator timed out",
                    "evidence_sha256": "a" * 64,
                },
            }
        )

        packet = evaluation_module.run_v4_floor_evidence_pipeline(
            manifest=manifest,
            finalized_runner_output_loader=build_floor_runner_output_loader(
                manifest,
                payloads=payloads,
            ),
            input_artifact_bytes=build_artifact_bytes(
                manifest,
                source_ledgers=source_ledgers,
            ),
            source_ledgers=source_ledgers,
            relation_label_ledgers=relation_ledgers,
        )

        runs = {run["variant_id"]: run for run in packet["runs"]}
        self.assertIsNone(runs["semantic_rerank"]["patch"])
        self.assertIsNone(runs["semantic_rerank"]["test_result"])
        self.assertEqual(runs["raw_full_history"]["designation"], "invalidated_technical")
        self.assertEqual(runs["raw_full_history"]["failure"]["code"], "sandbox_timeout")
        self.assertIsNone(packet["aggregate_report"])
        self.assertIsNone(packet["evidence_manifest"])
        self.assertEqual(packet["evidence_status"], "incomplete_retained_population")
        retained = packet["retained_attempt_loader"].load_finalized_population(
            packet["execution_manifest_sha256"]
        )
        self.assertEqual(retained["entry_count"], len(V4_VARIANTS))
        states = {
            entry["run_id"]: entry["finalization_state"]
            for entry in retained["entries"]
        }
        self.assertEqual(
            states[runs["raw_full_history"]["run_id"]],
            "invalidated_technical",
        )

    def test_v4_floor_retains_technical_attempt_before_accepted_replacement(self):
        source_ledger = build_source_ledger("diag-project-a")
        relation_ledger = build_relation_label_ledger(
            "diag-project-a", source_ledger, entries=[]
        )
        source_ledgers = {"diag-project-a": source_ledger}
        relation_ledgers = {"diag-project-a": relation_ledger}
        manifest = build_floor_execution_manifest(
            source_ledgers=source_ledgers,
            relation_label_ledgers=relation_ledgers,
        )
        payloads = build_floor_runner_payloads(manifest)
        replacement = copy.deepcopy(payloads["raw_full_history"])
        replacement["run_id"] = "eval_FloorRawReplacement"
        technical = copy.deepcopy(payloads["raw_full_history"])
        technical.update(
            {
                "run_id": "eval_FloorRawTimeout",
                "full_suite_passed": None,
                "test_result": None,
                "attempt_outcome": {
                    "status": "invalidated",
                    "stage": "sandbox",
                    "code": "technical_failure",
                },
                "failure": {
                    "code": "sandbox_timeout",
                    "detail": "isolated evaluator timed out and cleanup completed",
                    "evidence_sha256": "b" * 64,
                },
            }
        )

        packet = evaluation_module.run_v4_floor_evidence_pipeline(
            manifest=manifest,
            finalized_runner_output_loader=build_floor_runner_output_loader(
                manifest,
                payloads=payloads,
                attempts_by_variant={
                    "raw_full_history": [technical, replacement],
                },
            ),
            input_artifact_bytes=build_artifact_bytes(
                manifest,
                source_ledgers=source_ledgers,
            ),
            source_ledgers=source_ledgers,
            relation_label_ledgers=relation_ledgers,
        )

        self.assertEqual(len(packet["runs"]), len(V4_VARIANTS) + 1)
        retained = packet["retained_attempt_loader"].load_finalized_population(
            packet["execution_manifest_sha256"]
        )
        raw_entries = [
            entry
            for entry in retained["entries"]
            if entry["slot_index"] == manifest["execution_order"][0]["slot_index"]
        ]
        self.assertEqual(
            [entry["finalization_state"] for entry in raw_entries],
            ["invalidated_technical", "accepted"],
        )
        self.assertEqual([entry["attempt_no"] for entry in raw_entries], [1, 2])
        self.assertIsNotNone(packet["aggregate_report"])
        self.assertEqual(packet["evidence_status"], "partial_test_only_evidence")

    def test_v4_floor_rejects_accepted_replacement_after_manual_abort(self):
        source_ledger = build_source_ledger("diag-project-a")
        relation_ledger = build_relation_label_ledger(
            "diag-project-a", source_ledger, entries=[]
        )
        source_ledgers = {"diag-project-a": source_ledger}
        relation_ledgers = {"diag-project-a": relation_ledger}
        manifest = build_floor_execution_manifest(
            source_ledgers=source_ledgers,
            relation_label_ledgers=relation_ledgers,
        )
        payloads = build_floor_runner_payloads(manifest)
        aborted = copy.deepcopy(payloads["raw_full_history"])
        aborted.update(
            {
                "run_id": "eval_FloorRawManualAbort",
                "full_suite_passed": None,
                "test_result": None,
                "attempt_outcome": {
                    "status": "invalidated",
                    "stage": "aborted",
                    "code": "manual_abort",
                },
                "failure": {
                    "code": "manual_abort",
                    "detail": "operator aborted the claim-bearing cell",
                    "evidence_sha256": "b" * 64,
                },
            }
        )
        replacement = copy.deepcopy(payloads["raw_full_history"])
        replacement["run_id"] = "eval_FloorRawAfterManualAbort"

        with self.assertRaisesRegex(
            ValueError,
            "manual-abort runner attempt cannot be replaced",
        ):
            evaluation_module.run_v4_floor_evidence_pipeline(
                manifest=manifest,
                finalized_runner_output_loader=build_floor_runner_output_loader(
                    manifest,
                    payloads=payloads,
                    attempts_by_variant={
                        "raw_full_history": [aborted, replacement],
                    },
                ),
                input_artifact_bytes=build_artifact_bytes(
                    manifest,
                    source_ledgers=source_ledgers,
                ),
                source_ledgers=source_ledgers,
                relation_label_ledgers=relation_ledgers,
            )

    def test_v4_floor_retains_terminal_manual_abort_as_incomplete_evidence(self):
        source_ledger = build_source_ledger("diag-project-a")
        relation_ledger = build_relation_label_ledger(
            "diag-project-a", source_ledger, entries=[]
        )
        source_ledgers = {"diag-project-a": source_ledger}
        relation_ledgers = {"diag-project-a": relation_ledger}
        manifest = build_floor_execution_manifest(
            source_ledgers=source_ledgers,
            relation_label_ledgers=relation_ledgers,
        )
        payloads = build_floor_runner_payloads(manifest)
        aborted = payloads["raw_full_history"]
        aborted.update(
            {
                "run_id": "eval_FloorTerminalManualAbort",
                "full_suite_passed": None,
                "patch_diff": "",
                "original_files": [],
                "patched_files": [],
                "test_result": None,
                "attempt_outcome": {
                    "status": "invalidated",
                    "stage": "aborted",
                    "code": "manual_abort",
                },
                "failure": {
                    "code": "manual_abort",
                    "detail": "operator aborted the claim-bearing cell",
                    "evidence_sha256": "b" * 64,
                },
            }
        )

        packet = evaluation_module.run_v4_floor_evidence_pipeline(
            manifest=manifest,
            finalized_runner_output_loader=build_floor_runner_output_loader(
                manifest,
                payloads=payloads,
            ),
            input_artifact_bytes=build_artifact_bytes(
                manifest,
                source_ledgers=source_ledgers,
            ),
            source_ledgers=source_ledgers,
            relation_label_ledgers=relation_ledgers,
        )

        aborted_run = next(
            run for run in packet["runs"] if run["variant_id"] == "raw_full_history"
        )
        self.assertEqual(aborted_run["designation"], "invalidated_abort")
        self.assertEqual(aborted_run["failure"]["code"], "manual_abort")
        self.assertIsNone(packet["aggregate_report"])
        self.assertIsNone(packet["evidence_manifest"])
        self.assertEqual(packet["evidence_status"], "incomplete_retained_population")

    def test_v4_floor_rejects_production_binding_from_another_manifest_attempt(self):
        source_ledger = build_source_ledger("diag-project-a")
        relation_ledger = build_relation_label_ledger(
            "diag-project-a", source_ledger, entries=[]
        )
        source_ledgers = {"diag-project-a": source_ledger}
        relation_ledgers = {"diag-project-a": relation_ledger}
        manifest = build_floor_execution_manifest(
            source_ledgers=source_ledgers,
            relation_label_ledgers=relation_ledgers,
        )
        payloads = build_floor_runner_payloads(manifest)
        slot = manifest["execution_order"][0]
        payloads["raw_full_history"]["runtime_trace"]["execution_binding"] = {
            "authority_mode": "production_docker",
            "execution_manifest_sha256": "0" * 64,
            "scenario_id": slot["scenario_slot"],
            "slot_index": slot["slot_index"],
            "attempt_no": slot["repetition"] + 1,
        }

        with self.assertRaisesRegex(
            ValueError,
            "production execution binding does not match the current manifest slot attempt",
        ):
            evaluation_module.run_v4_floor_evidence_pipeline(
                manifest=manifest,
                finalized_runner_output_loader=build_floor_runner_output_loader(
                    manifest,
                    payloads=payloads,
                ),
                input_artifact_bytes=build_artifact_bytes(
                    manifest,
                    source_ledgers=source_ledgers,
                ),
                source_ledgers=source_ledgers,
                relation_label_ledgers=relation_ledgers,
            )

    def test_v4_floor_rejects_replacing_accepted_or_chaining_technical_attempts(self):
        source_ledger = build_source_ledger("diag-project-a")
        relation_ledger = build_relation_label_ledger(
            "diag-project-a", source_ledger, entries=[]
        )
        source_ledgers = {"diag-project-a": source_ledger}
        relation_ledgers = {"diag-project-a": relation_ledger}
        manifest = build_floor_execution_manifest(
            source_ledgers=source_ledgers,
            relation_label_ledgers=relation_ledgers,
        )
        payloads = build_floor_runner_payloads(manifest)

        accepted = copy.deepcopy(payloads["raw_full_history"])
        accepted_replacement = copy.deepcopy(accepted)
        accepted_replacement["run_id"] = "eval_FloorRawDuplicate"
        with self.assertRaisesRegex(ValueError, "invalid_retained_population"):
            evaluation_module.run_v4_floor_evidence_pipeline(
                manifest=manifest,
                finalized_runner_output_loader=build_floor_runner_output_loader(
                    manifest,
                    payloads=payloads,
                    attempts_by_variant={
                        "raw_full_history": [accepted, accepted_replacement],
                    },
                ),
                input_artifact_bytes=build_artifact_bytes(
                    manifest,
                    source_ledgers=source_ledgers,
                ),
                source_ledgers=source_ledgers,
                relation_label_ledgers=relation_ledgers,
            )

        technical_attempts = []
        for index in range(2):
            technical = copy.deepcopy(payloads["raw_full_history"])
            technical.update(
                {
                    "run_id": f"eval_FloorRawTimeout{index}",
                    "full_suite_passed": None,
                    "test_result": None,
                    "attempt_outcome": {
                        "status": "invalidated",
                        "stage": "sandbox",
                        "code": "technical_failure",
                    },
                    "failure": {
                        "code": "sandbox_timeout",
                        "detail": "isolated evaluator timed out",
                        "evidence_sha256": str(index + 1) * 64,
                    },
                }
            )
            technical_attempts.append(technical)

        with self.assertRaisesRegex(ValueError, "invalid_retained_population"):
            evaluation_module.run_v4_floor_evidence_pipeline(
                manifest=manifest,
                finalized_runner_output_loader=build_floor_runner_output_loader(
                    manifest,
                    payloads=payloads,
                    attempts_by_variant={
                        "raw_full_history": technical_attempts,
                    },
                ),
                input_artifact_bytes=build_artifact_bytes(
                    manifest,
                    source_ledgers=source_ledgers,
                ),
                source_ledgers=source_ledgers,
                relation_label_ledgers=relation_ledgers,
            )

    def test_v4_floor_formal_pipeline_derives_unscored_metrics(self):
        source_ledger = build_source_ledger("diag-project-a")
        relation_ledger = build_relation_label_ledger(
            "diag-project-a", source_ledger, entries=[]
        )
        manifest = build_floor_execution_manifest(
            source_ledgers={"diag-project-a": source_ledger},
            relation_label_ledgers={"diag-project-a": relation_ledger},
        )
        payloads = build_floor_runner_payloads(manifest)
        payloads["raw_full_history"]["metrics"] = {
            "required_total": 1_000_000,
        }
        with self.assertRaisesRegex(ValueError, "invalid_run_reference"):
            evaluation_module.run_v4_floor_evidence_pipeline(
                manifest=manifest,
                finalized_runner_output_loader=build_floor_runner_output_loader(
                    manifest,
                    payloads=payloads,
                ),
                input_artifact_bytes=build_artifact_bytes(
                    manifest,
                    source_ledgers={"diag-project-a": source_ledger},
                ),
                source_ledgers={"diag-project-a": source_ledger},
                relation_label_ledgers={"diag-project-a": relation_ledger},
            )

        packet = evaluation_module.run_v4_floor_evidence_pipeline(
            manifest=manifest,
            finalized_runner_output_loader=build_floor_runner_output_loader(manifest),
            input_artifact_bytes=build_artifact_bytes(
                manifest,
                source_ledgers={"diag-project-a": source_ledger},
            ),
            source_ledgers={"diag-project-a": source_ledger},
            relation_label_ledgers={"diag-project-a": relation_ledger},
        )
        self.assertTrue(
            all(
                run["metrics"]
                == {
                    "stale_selected": 0,
                    "selected_total": len(run["selected_sources"]),
                    "required_selected": 0,
                    "required_total": 0,
                    "candidate_prior_selected": 0,
                    "candidate_prior_total": 0,
                }
                for run in packet["runs"]
            )
        )

    def test_v4_floor_formal_pipeline_rejects_caller_wrapped_runner_snapshot(self):
        source_ledger = build_source_ledger("diag-project-a")
        relation_ledger = build_relation_label_ledger(
            "diag-project-a", source_ledger, entries=[]
        )
        manifest = build_floor_execution_manifest(
            source_ledgers={"diag-project-a": source_ledger},
            relation_label_ledgers={"diag-project-a": relation_ledger},
        )
        trusted_loader = build_floor_runner_output_loader(manifest)

        class CallerWrappedLoader:
            def load_finalized_runner_outputs(self, manifest_sha256):
                return trusted_loader.load_finalized_runner_outputs(manifest_sha256)

        with self.assertRaisesRegex(ValueError, "invalid_retained_population"):
            evaluation_module.run_v4_floor_evidence_pipeline(
                manifest=manifest,
                finalized_runner_output_loader=CallerWrappedLoader(),
                input_artifact_bytes=build_artifact_bytes(
                    manifest,
                    source_ledgers={"diag-project-a": source_ledger},
                ),
                source_ledgers={"diag-project-a": source_ledger},
                relation_label_ledgers={"diag-project-a": relation_ledger},
            )

    def test_v4_floor_generic_aggregate_rejects_caller_wrapped_retained_loader(self):
        source_ledger = build_source_ledger("diag-project-a")
        relation_ledger = build_relation_label_ledger(
            "diag-project-a", source_ledger, entries=[]
        )
        source_ledgers = {"diag-project-a": source_ledger}
        relation_ledgers = {"diag-project-a": relation_ledger}
        manifest = build_floor_execution_manifest(
            source_ledgers=source_ledgers,
            relation_label_ledgers=relation_ledgers,
        )
        packet = evaluation_module.run_v4_floor_evidence_pipeline(
            manifest=manifest,
            finalized_runner_output_loader=build_floor_runner_output_loader(manifest),
            input_artifact_bytes=build_artifact_bytes(
                manifest,
                source_ledgers=source_ledgers,
            ),
            source_ledgers=source_ledgers,
            relation_label_ledgers=relation_ledgers,
        )

        class CallerWrappedLoader:
            def load_finalized_population(self, manifest_sha256):
                return packet["retained_attempt_loader"].load_finalized_population(
                    manifest_sha256
                )

        with self.assertRaisesRegex(ValueError, "invalid_aggregate"):
            validate_aggregate_report(
                packet["aggregate_report"],
                execution_manifest=manifest,
                retained_attempt_loader=CallerWrappedLoader(),
                artifact_bytes=packet["artifact_bytes"],
                source_ledgers=source_ledgers,
                relation_label_ledgers=relation_ledgers,
            )

        forged_snapshot = packet["retained_attempt_loader"].load_finalized_population(
            packet["execution_manifest_sha256"]
        )
        forged_snapshot["authority_kind"] = "production_append_only_attempt_journal"
        forged_snapshot.pop("simulation_marker")
        with self.assertRaisesRegex(ValueError, "invalid_aggregate"):
            validate_aggregate_report(
                packet["aggregate_report"],
                execution_manifest=manifest,
                retained_attempt_loader=TestOnlyTrustedRetainedAttemptLoader(
                    forged_snapshot
                ),
                artifact_bytes=packet["artifact_bytes"],
                source_ledgers=source_ledgers,
                relation_label_ledgers=relation_ledgers,
            )

    def test_v4_floor_test_simulation_cannot_enable_final_claim(self):
        source_ledger = build_source_ledger("diag-project-a")
        relation_ledger = build_relation_label_ledger(
            "diag-project-a", source_ledger, entries=[]
        )
        manifest = build_floor_execution_manifest(
            source_ledgers={"diag-project-a": source_ledger},
            relation_label_ledgers={"diag-project-a": relation_ledger},
        )
        packet = evaluation_module.run_v4_floor_evidence_pipeline(
            manifest=manifest,
            finalized_runner_output_loader=build_floor_runner_output_loader(manifest),
            input_artifact_bytes=build_artifact_bytes(
                manifest,
                source_ledgers={"diag-project-a": source_ledger},
            ),
            source_ledgers={"diag-project-a": source_ledger},
            relation_label_ledgers={"diag-project-a": relation_ledger},
        )

        evidence = packet["evidence_manifest"]
        self.assertEqual(evidence["status"], "partial")
        self.assertEqual(evidence["aggregate_ids"], [])
        self.assertEqual(evidence["claims"][0]["status"], "disabled")
        self.assertEqual(
            evidence["claims"][0]["decision_reason"], "evidence_incomplete"
        )
        self.assertEqual(evidence["claims"][0]["evidence_artifact_ids"], [])

    def test_v4_floor_test_simulation_cannot_be_replayed_as_final_evidence(self):
        source_ledger = build_source_ledger("diag-project-a")
        relation_ledger = build_relation_label_ledger(
            "diag-project-a", source_ledger, entries=[]
        )
        source_ledgers = {"diag-project-a": source_ledger}
        relation_ledgers = {"diag-project-a": relation_ledger}
        manifest = build_floor_execution_manifest(
            source_ledgers=source_ledgers,
            relation_label_ledgers=relation_ledgers,
        )
        packet = evaluation_module.run_v4_floor_evidence_pipeline(
            manifest=manifest,
            finalized_runner_output_loader=build_floor_runner_output_loader(manifest),
            input_artifact_bytes=build_artifact_bytes(
                manifest,
                source_ledgers=source_ledgers,
            ),
            source_ledgers=source_ledgers,
            relation_label_ledgers=relation_ledgers,
        )

        forged = copy.deepcopy(packet["evidence_manifest"])
        aggregate = packet["aggregate_report"]
        aggregate_id = aggregate["aggregate_id"]
        aggregate_bytes = packet["artifact_bytes"][aggregate_id]
        forged["status"] = "final"
        forged["aggregate_ids"] = [aggregate_id]
        forged["output_artifact_catalog"][aggregate_id] = {
            "kind": "aggregate_report",
            "relative_path": f"aggregates/{aggregate_id}.json",
            "sha256": hashlib.sha256(aggregate_bytes).hexdigest(),
            "bytes": len(aggregate_bytes),
            "sanitized": True,
            "content_policy": "sanitized_bounded",
        }
        forged["claims"][0]["status"] = "enabled"
        forged["claims"][0]["decision_reason"] = "threshold_passed"
        forged["claims"][0]["evidence_artifact_ids"] = [aggregate_id]

        with self.assertRaisesRegex(ValueError, "incomplete_final_evidence"):
            validate_evidence_manifest(
                forged,
                manifest,
                retained_attempt_loader=packet["retained_attempt_loader"],
                artifact_bytes=packet["artifact_bytes"],
                source_ledgers=source_ledgers,
                relation_label_ledgers=relation_ledgers,
            )

    def test_v4_floor_formal_pipeline_rejects_diff_sidecar_divergence(self):
        source_ledger = build_source_ledger("diag-project-a")
        relation_ledger = build_relation_label_ledger(
            "diag-project-a", source_ledger, entries=[]
        )
        manifest = build_floor_execution_manifest(
            source_ledgers={"diag-project-a": source_ledger},
            relation_label_ledgers={"diag-project-a": relation_ledger},
        )
        payloads = build_floor_runner_payloads(manifest)
        payloads["raw_full_history"]["patch_diff"] = (
            "--- a/src/retry.py\n+++ b/src/retry.py\n@@ -1 +1 @@\n-old\n+unrelated\n"
        )
        with self.assertRaisesRegex(ValueError, "invalid_patch_result"):
            evaluation_module.run_v4_floor_evidence_pipeline(
                manifest=manifest,
                finalized_runner_output_loader=build_floor_runner_output_loader(
                    manifest, payloads=payloads
                ),
                input_artifact_bytes=build_artifact_bytes(
                    manifest,
                    source_ledgers={"diag-project-a": source_ledger},
                ),
                source_ledgers={"diag-project-a": source_ledger},
                relation_label_ledgers={"diag-project-a": relation_ledger},
            )

    def test_v4_floor_generic_aggregate_boundary_rejects_quality_metric(self):
        source_ledger = build_source_ledger("diag-project-a")
        relation_ledger = build_relation_label_ledger(
            "diag-project-a", source_ledger, entries=[]
        )
        source_ledgers = {"diag-project-a": source_ledger}
        relation_ledgers = {"diag-project-a": relation_ledger}
        manifest = build_floor_execution_manifest(
            source_ledgers=source_ledgers,
            relation_label_ledgers=relation_ledgers,
        )
        packet = evaluation_module.run_v4_floor_evidence_pipeline(
            manifest=manifest,
            finalized_runner_output_loader=build_floor_runner_output_loader(manifest),
            input_artifact_bytes=build_artifact_bytes(
                manifest,
                source_ledgers=source_ledgers,
            ),
            source_ledgers=source_ledgers,
            relation_label_ledgers=relation_ledgers,
        )
        aggregate = copy.deepcopy(packet["aggregate_report"])
        selected_total = sum(
            run["metrics"]["selected_total"] for run in packet["runs"]
        )
        aggregate["metrics"] = [
            {
                "metric_id": "stale_leakage_rate",
                "n": selected_total,
                "numerator": 0,
                "denominator": selected_total,
                "rate": 0.0,
            }
        ]
        with self.assertRaisesRegex(ValueError, "invalid_aggregate"):
            validate_aggregate_report(
                aggregate,
                execution_manifest=manifest,
                retained_attempt_loader=packet["retained_attempt_loader"],
                artifact_bytes=packet["artifact_bytes"],
                source_ledgers=source_ledgers,
                relation_label_ledgers=relation_ledgers,
            )


if __name__ == "__main__":
    unittest.main()
