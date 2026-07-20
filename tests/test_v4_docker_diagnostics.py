from __future__ import annotations

import importlib
import json
import shutil
import subprocess
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

import recallpack.evaluation_docker as docker_module
import recallpack.isolation as isolation_module
from recallpack.evaluation import execute_v4_diagnostic_variants
from recallpack.evaluation_docker import (
    build_runtime_evaluator_contract,
    run_v4_isolated_diagnostic_variants,
    sandbox_evidence_from_contract,
    validate_isolated_result,
)
from recallpack.evaluation_evidence_adapter import build_v4_diagnostic_runner_outputs
from recallpack.isolation import (
    IsolatedExecutionBinding,
    IsolatedSuiteResult,
    ProductionExecutionIdentity,
    SAFE_COMMAND,
)


ROOT = Path(__file__).resolve().parents[1]
SCENARIO_ROOT = ROOT / "evaluation" / "scenarios" / "projectodyssey"
FIXTURE_ROOT = ROOT / "fixtures" / "project-h-projectodyssey-jit"
HIDDEN_TEST_ROOT = ROOT / "evaluation" / "hidden-tests" / "projectodyssey"
IMAGE_DIGEST = "sha256:" + "1" * 64
BASE_IMAGE_DIGEST = "sha256:" + "2" * 64


class _CapturingIsolatedRunner:
    def __init__(self) -> None:
        self.calls = []

    def __call__(self, **kwargs):
        self.calls.append(kwargs)
        repository_root = Path(kwargs["repository_root"])
        source = (repository_root / "src" / "ci_policy.py").read_text()
        passed = "fail_and_fix_forward" in source
        statuses = ["passed", "passed", "passed"] if passed else [
            "failed",
            "failed",
            "passed",
        ]
        tests = [
            {
                "name": "network_probe",
                "status": "passed",
                "duration_ms": 1,
                "evidence_artifact_id": "runner_result_json",
            },
            *[
                {
                    "name": f"tests.test_policy.PolicyTests.test_{index}",
                    "status": status,
                    "duration_ms": index,
                    "evidence_artifact_id": "runner_result_json",
                }
                for index, status in enumerate(statuses, start=1)
            ],
        ]
        passed_count = sum(item["status"] == "passed" for item in tests)
        failed_count = sum(item["status"] == "failed" for item in tests)
        payload = {
            "tests": tests,
            "full_suite_passed": failed_count == 0,
            "passed": passed_count,
            "failed": failed_count,
            "exit_code": 0 if failed_count == 0 else 1,
            "timed_out": False,
        }
        return IsolatedSuiteResult(
            exit_code=payload["exit_code"],
            stdout=json.dumps(payload, sort_keys=True, separators=(",", ":")),
            stderr="",
            json_result=payload,
            blocked=False,
            timed_out=False,
            failure_code=None,
            host_fallback_used=False,
        )


class V4DockerDiagnosticTests(unittest.TestCase):
    def test_production_identity_names_frozen_repository_and_hidden_test_digests(self):
        fields = set(ProductionExecutionIdentity.__dataclass_fields__)

        self.assertIn("repository_snapshot_sha256", fields)
        self.assertIn("hidden_test_tree_sha256", fields)

    def test_production_receipt_is_bound_to_manifest_slot_and_attempt_identity(self):
        isolation = importlib.import_module("recallpack.isolation")
        identity_type = getattr(isolation, "ProductionExecutionIdentity", None)
        self.assertIsNotNone(
            identity_type,
            "production execution identity must be a closed runtime type",
        )
        identity = identity_type(
            execution_manifest_sha256="1" * 64,
            scenario_id="projectodyssey",
            slot_index=4,
            attempt_no=1,
            repository_snapshot_sha256="b" * 64,
            hidden_test_tree_sha256="c" * 64,
        )
        payload = {
            "tests": [
                {
                    "name": "network_probe",
                    "status": "passed",
                    "duration_ms": 1,
                    "evidence_artifact_id": "runner_result_json",
                },
                {
                    "name": "tests.test_policy.PolicyTests.test_policy",
                    "status": "passed",
                    "duration_ms": 1,
                    "evidence_artifact_id": "runner_result_json",
                },
            ],
            "full_suite_passed": True,
            "passed": 2,
            "failed": 0,
            "exit_code": 0,
            "timed_out": False,
        }

        class SuccessfulDockerRunner:
            def __call__(self, argv, *, env, timeout, capture_output, text, check):
                del env, timeout, capture_output, text, check
                return subprocess.CompletedProcess(
                    args=argv,
                    returncode=0,
                    stdout=json.dumps(payload, sort_keys=True, separators=(",", ":")),
                    stderr="",
                )

        runner = SuccessfulDockerRunner()
        contract = build_runtime_evaluator_contract(
            platform="linux/arm64",
            image_digest=IMAGE_DIGEST,
            base_image_digest=BASE_IMAGE_DIGEST,
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir).resolve()
            repository_root = root / "repo"
            hidden_test_root = root / "hidden"
            repository_root.mkdir()
            hidden_test_root.mkdir()
            container_name = "recallpack-eval-identity-test"
            argv, _ = isolation.build_docker_argv(
                evaluator_contract=contract,
                image_digest=IMAGE_DIGEST,
                repository_root=repository_root,
                hidden_test_root=hidden_test_root,
                command=SAFE_COMMAND,
                container_name=container_name,
            )
            binding = IsolatedExecutionBinding(
                variant_id="recallpack",
                patch_sha256="a" * 64,
                repository_tree_sha256="b" * 64,
                hidden_test_tree_sha256="c" * 64,
                execution_nonce="identity-test-nonce",
                docker_argv_sha256=isolation.execution_invocation_sha256(
                    argv=argv,
                    variant_id="recallpack",
                    patch_sha256="a" * 64,
                    repository_tree_sha256="b" * 64,
                    hidden_test_tree_sha256="c" * 64,
                    execution_nonce="identity-test-nonce",
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
            original_run = isolation.subprocess.run
            isolation.subprocess.run = runner
            try:
                result = isolation.run_isolated_suite(
                    evaluator_contract=contract,
                    image_digest=IMAGE_DIGEST,
                    repository_root=repository_root,
                    hidden_test_root=hidden_test_root,
                    command=SAFE_COMMAND,
                    docker_runner=runner,
                    docker_cleanup_runner=runner,
                    container_name=container_name,
                    execution_binding=binding,
                )
            finally:
                isolation.subprocess.run = original_run

        self.assertTrue(
            isolation.has_valid_production_execution_receipt(
                result,
                expected_identity=identity,
            )
        )
        self.assertFalse(
            isolation.has_valid_production_execution_receipt(
                result,
                expected_identity=replace(identity, attempt_no=2),
            )
        )
        self.assertFalse(
            isolation.has_valid_production_execution_receipt(
                result,
                expected_identity=replace(
                    identity,
                    execution_manifest_sha256="2" * 64,
                ),
            )
        )

    def test_public_dataclasses_cannot_forge_a_production_docker_receipt(self):
        payload = {
            "tests": [
                {
                    "name": "network_probe",
                    "status": "passed",
                    "duration_ms": 1,
                    "evidence_artifact_id": "runner_result_json",
                },
                {
                    "name": "tests.test_policy.PolicyTests.test_policy",
                    "status": "passed",
                    "duration_ms": 1,
                    "evidence_artifact_id": "runner_result_json",
                },
            ],
            "full_suite_passed": True,
            "passed": 2,
            "failed": 0,
            "exit_code": 0,
            "timed_out": False,
        }
        forged = IsolatedSuiteResult(
            exit_code=0,
            stdout=json.dumps(payload, sort_keys=True, separators=(",", ":")),
            stderr="",
            json_result=payload,
            blocked=False,
            timed_out=False,
            failure_code=None,
            host_fallback_used=False,
            container_name="recallpack-eval-forged",
            execution_binding=IsolatedExecutionBinding(
                variant_id="recallpack",
                patch_sha256="a" * 64,
                repository_tree_sha256="b" * 64,
                hidden_test_tree_sha256="c" * 64,
                execution_nonce="caller-chosen",
                docker_argv_sha256="d" * 64,
                authority_mode="production_docker",
            ),
        )

        with self.assertRaisesRegex(ValueError, "execution receipt"):
            validate_isolated_result(forged)

    def test_each_variant_runs_its_applied_patch_through_isolated_suite_contract(self):
        diagnostic = execute_v4_diagnostic_variants(
            scenario_root=SCENARIO_ROOT,
            fixture_root=FIXTURE_ROOT,
        )
        contract = build_runtime_evaluator_contract(
            platform="linux/arm64",
            image_digest=IMAGE_DIGEST,
            base_image_digest=BASE_IMAGE_DIGEST,
        )
        runner = _CapturingIsolatedRunner()

        isolated = run_v4_isolated_diagnostic_variants(
            diagnostic,
            fixture_root=FIXTURE_ROOT,
            hidden_test_root=HIDDEN_TEST_ROOT,
            evaluator_contract=contract,
            suite_runner=runner,
        )

        self.assertEqual(set(isolated), set(diagnostic.variants))
        self.assertEqual(len(runner.calls), 5)
        self.assertFalse(isolated["raw_full_history"].json_result["full_suite_passed"])
        self.assertFalse(isolated["semantic_rerank"].json_result["full_suite_passed"])
        self.assertTrue(isolated["recency_aware"].json_result["full_suite_passed"])
        self.assertTrue(isolated["recall_time_resolver"].json_result["full_suite_passed"])
        self.assertTrue(isolated["recallpack"].json_result["full_suite_passed"])
        repository_roots = [Path(call["repository_root"]) for call in runner.calls]
        self.assertEqual(len(repository_roots), len(set(repository_roots)))
        self.assertTrue(all(call["command"] == SAFE_COMMAND for call in runner.calls))
        self.assertTrue(
            all(call["image_digest"] == IMAGE_DIGEST for call in runner.calls)
        )
        self.assertTrue(all(not root.exists() for root in repository_roots))
        hidden_hashes = {
            item.execution_binding.hidden_test_tree_sha256
            for item in isolated.values()
        }
        self.assertEqual(len(hidden_hashes), 1)
        self.assertTrue(
            all(
                item.execution_binding.variant_id == variant_id
                and item.execution_binding.patch_sha256
                and item.execution_binding.repository_tree_sha256
                and item.execution_binding.execution_nonce
                and item.execution_binding.authority_mode
                == "test_only_injected_runner"
                for variant_id, item in isolated.items()
            )
        )

    def test_production_grid_rejects_fixture_or_hidden_test_mutation_between_variants(
        self,
    ):
        diagnostic = execute_v4_diagnostic_variants(
            scenario_root=SCENARIO_ROOT,
            fixture_root=FIXTURE_ROOT,
        )
        contract = build_runtime_evaluator_contract(
            platform="linux/arm64",
            image_digest=IMAGE_DIGEST,
            base_image_digest=BASE_IMAGE_DIGEST,
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            fixture_root = root / "fixture"
            hidden_test_root = root / "hidden-tests"
            shutil.copytree(FIXTURE_ROOT, fixture_root)
            shutil.copytree(HIDDEN_TEST_ROOT, hidden_test_root)
            repository_snapshot = fixture_root / "repo_snapshot"
            repository_sha256 = docker_module._directory_tree_sha256(
                repository_snapshot
            )
            hidden_test_sha256 = docker_module._directory_tree_sha256(
                hidden_test_root
            )
            identities = {
                variant_id: ProductionExecutionIdentity(
                    execution_manifest_sha256="a" * 64,
                    scenario_id=diagnostic.scenario_id,
                    slot_index=index,
                    attempt_no=1,
                    repository_snapshot_sha256=repository_sha256,
                    hidden_test_tree_sha256=hidden_test_sha256,
                )
                for index, variant_id in enumerate(diagnostic.variants, start=1)
            }

            class MutatingRunner(_CapturingIsolatedRunner):
                def __call__(self, **kwargs):
                    result = super().__call__(**kwargs)
                    if len(self.calls) == 1:
                        source_path = repository_snapshot / "src" / "ci_policy.py"
                        source_path.write_text(
                            source_path.read_text(encoding="utf-8")
                            + "\n# concurrent mutation\n",
                            encoding="utf-8",
                        )
                        hidden_path = next(hidden_test_root.rglob("*.py"))
                        hidden_path.write_text(
                            hidden_path.read_text(encoding="utf-8")
                            + "\n# concurrent mutation\n",
                            encoding="utf-8",
                        )
                    return result

            runner = MutatingRunner()
            with (
                patch.object(docker_module, "run_isolated_suite", runner),
                patch.object(docker_module, "validate_isolated_result"),
            ):
                with self.assertRaisesRegex(
                    ValueError,
                    "frozen repository or hidden-test tree changed during execution",
                ):
                    run_v4_isolated_diagnostic_variants(
                        diagnostic,
                        fixture_root=fixture_root,
                        hidden_test_root=hidden_test_root,
                        evaluator_contract=contract,
                        suite_runner=runner,
                        production_execution_identities=identities,
                    )

    def test_sandbox_evidence_is_derived_exactly_from_runtime_contract(self):
        contract = build_runtime_evaluator_contract(
            platform="linux/arm64",
            image_digest=IMAGE_DIGEST,
            base_image_digest=BASE_IMAGE_DIGEST,
        )

        evidence = sandbox_evidence_from_contract(contract)

        self.assertEqual(evidence["platform"], "linux/arm64")
        self.assertEqual(evidence["image_digest"], IMAGE_DIGEST)
        self.assertEqual(evidence["base_image_digest"], BASE_IMAGE_DIGEST)
        self.assertTrue(evidence["network_none"])
        self.assertTrue(evidence["read_only_root"])
        self.assertTrue(evidence["drop_all_capabilities"])
        self.assertTrue(evidence["no_new_privileges"])
        self.assertEqual(evidence["repository_mount_mode"], "rw")
        self.assertEqual(evidence["hidden_test_mount_mode"], "ro")
        self.assertEqual(len(evidence), 20)

    def test_rejected_patch_is_retained_and_does_not_abort_remaining_grid(self):
        diagnostic = execute_v4_diagnostic_variants(
            scenario_root=SCENARIO_ROOT,
            fixture_root=FIXTURE_ROOT,
        )
        rejected_variant = replace(
            diagnostic.variants["semantic_rerank"],
            generated_files=[],
            downstream={
                **diagnostic.variants["semantic_rerank"].downstream,
                "accepted": False,
                "error": "empty_patch",
                "patch_diff": "",
                "test_status": "not_run_patch_rejected",
            },
        )
        diagnostic = replace(
            diagnostic,
            variants={**diagnostic.variants, "semantic_rerank": rejected_variant},
        )
        contract = build_runtime_evaluator_contract(
            platform="linux/arm64",
            image_digest=IMAGE_DIGEST,
            base_image_digest=BASE_IMAGE_DIGEST,
        )
        runner = _CapturingIsolatedRunner()

        isolated = run_v4_isolated_diagnostic_variants(
            diagnostic,
            fixture_root=FIXTURE_ROOT,
            hidden_test_root=HIDDEN_TEST_ROOT,
            evaluator_contract=contract,
            suite_runner=runner,
        )

        self.assertEqual(set(isolated), set(diagnostic.variants))
        self.assertEqual(len(runner.calls), 4)
        rejected = isolated["semantic_rerank"]
        self.assertTrue(rejected.blocked)
        self.assertEqual(rejected.failure_code, "empty_patch")
        self.assertEqual(rejected.execution_binding.variant_id, "semantic_rerank")
        self.assertEqual(
            rejected.execution_binding.authority_mode,
            "test_only_patch_not_executed",
        )

    def test_production_rejected_patch_has_authenticated_nonexecution_receipt(self):
        diagnostic = execute_v4_diagnostic_variants(
            scenario_root=SCENARIO_ROOT,
            fixture_root=FIXTURE_ROOT,
        )
        rejected_variant = replace(
            diagnostic.variants["semantic_rerank"],
            generated_files=[],
            downstream={
                **diagnostic.variants["semantic_rerank"].downstream,
                "accepted": False,
                "error": "empty_patch",
                "patch_diff": "",
                "test_status": "not_run_patch_rejected",
            },
        )
        diagnostic = replace(
            diagnostic,
            variants={"semantic_rerank": rejected_variant},
        )
        repository_sha256 = docker_module._directory_tree_sha256(
            FIXTURE_ROOT / "repo_snapshot"
        )
        hidden_test_sha256 = docker_module._directory_tree_sha256(HIDDEN_TEST_ROOT)
        identity = ProductionExecutionIdentity(
            execution_manifest_sha256="a" * 64,
            scenario_id=diagnostic.scenario_id,
            slot_index=1,
            attempt_no=1,
            repository_snapshot_sha256=repository_sha256,
            hidden_test_tree_sha256=hidden_test_sha256,
        )
        contract = build_runtime_evaluator_contract(
            platform="linux/arm64",
            image_digest=IMAGE_DIGEST,
            base_image_digest=BASE_IMAGE_DIGEST,
        )
        runner = _CapturingIsolatedRunner()

        with patch.object(docker_module, "run_isolated_suite", runner):
            isolated = run_v4_isolated_diagnostic_variants(
                diagnostic,
                fixture_root=FIXTURE_ROOT,
                hidden_test_root=HIDDEN_TEST_ROOT,
                evaluator_contract=contract,
                suite_runner=runner,
                production_execution_identities={
                    "semantic_rerank": identity,
                },
            )

        rejected = isolated["semantic_rerank"]
        self.assertEqual(runner.calls, [])
        self.assertTrue(
            isolation_module.has_valid_production_execution_receipt(
                rejected,
                expected_identity=identity,
            )
        )
        output = build_v4_diagnostic_runner_outputs(
            diagnostic,
            fixture_root=FIXTURE_ROOT,
            isolated_results={"semantic_rerank": rejected},
            evaluator_contract=contract,
            production_execution_identities={"semantic_rerank": identity},
        )["semantic_rerank"]
        self.assertEqual(
            output["attempt_outcome"],
            {
                "status": "adverse",
                "stage": "patch_generation",
                "code": "empty_patch",
            },
        )

    def test_runner_output_separates_model_and_sandbox_latency(self):
        diagnostic = execute_v4_diagnostic_variants(
            scenario_root=SCENARIO_ROOT,
            fixture_root=FIXTURE_ROOT,
        )
        variant = diagnostic.variants["recallpack"]
        measured_provider_latency = 17
        diagnostic = replace(
            diagnostic,
            variants={
                "recallpack": replace(
                    variant,
                    provider_traces=[
                        {**trace, "latency_ms": measured_provider_latency}
                        for trace in variant.provider_traces
                    ],
                )
            },
        )
        contract = build_runtime_evaluator_contract(
            platform="linux/arm64",
            image_digest=IMAGE_DIGEST,
            base_image_digest=BASE_IMAGE_DIGEST,
        )
        runner = _CapturingIsolatedRunner()

        isolated = run_v4_isolated_diagnostic_variants(
            diagnostic,
            fixture_root=FIXTURE_ROOT,
            hidden_test_root=HIDDEN_TEST_ROOT,
            evaluator_contract=contract,
            suite_runner=runner,
        )

        output = build_v4_diagnostic_runner_outputs(
            diagnostic,
            fixture_root=FIXTURE_ROOT,
            isolated_results=isolated,
            evaluator_contract=contract,
        )["recallpack"]
        model_latency = measured_provider_latency * len(variant.provider_traces)
        self.assertEqual(
            {
                "total": model_latency + 7,
                "stages": {"model": model_latency, "sandbox": 7},
            },
            output["latency_ms"],
        )

    def test_sandbox_technical_failure_is_retained_and_grid_continues(self):
        diagnostic = execute_v4_diagnostic_variants(
            scenario_root=SCENARIO_ROOT,
            fixture_root=FIXTURE_ROOT,
        )
        contract = build_runtime_evaluator_contract(
            platform="linux/arm64",
            image_digest=IMAGE_DIGEST,
            base_image_digest=BASE_IMAGE_DIGEST,
        )

        class FirstTimeoutThenSuccess(_CapturingIsolatedRunner):
            def __call__(self, **kwargs):
                if not self.calls:
                    self.calls.append(kwargs)
                    return IsolatedSuiteResult(
                        exit_code=None,
                        stdout="",
                        stderr="timeout",
                        json_result=None,
                        blocked=True,
                        timed_out=True,
                        failure_code="sandbox_timeout",
                        host_fallback_used=False,
                        container_name="recallpack-eval-timeout-test",
                        cleanup_attempted=True,
                        cleanup_succeeded=True,
                    )
                return super().__call__(**kwargs)

        runner = FirstTimeoutThenSuccess()
        isolated = run_v4_isolated_diagnostic_variants(
            diagnostic,
            fixture_root=FIXTURE_ROOT,
            hidden_test_root=HIDDEN_TEST_ROOT,
            evaluator_contract=contract,
            suite_runner=runner,
        )

        self.assertEqual(set(isolated), set(diagnostic.variants))
        self.assertEqual(len(runner.calls), 5)
        timeout = isolated["raw_full_history"]
        self.assertTrue(timeout.blocked)
        self.assertEqual(timeout.failure_code, "sandbox_timeout")
        self.assertEqual(timeout.execution_binding.variant_id, "raw_full_history")


if __name__ == "__main__":
    unittest.main()
