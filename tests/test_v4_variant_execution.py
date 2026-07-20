import hashlib
import json
import shutil
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import recallpack.evaluation_variants as variant_module
import recallpack.evaluation_docker as docker_module
import recallpack.isolation as isolation_module
from recallpack.budget import count_canonical_json_tokens
from recallpack.downstream import (
    DeterministicPolicyPatchProvider,
    PatchGenerationRequest,
)
from recallpack.evaluation import (
    build_v4_diagnostic_runner_outputs,
    execute_v4_diagnostic_variants,
)
from recallpack.evaluation_docker import (
    build_runtime_evaluator_contract,
    sandbox_evidence_from_contract,
)
from recallpack.evidence_pipeline import _validate_runner_execution_identity
from recallpack.isolation import IsolatedSuiteResult, ProductionExecutionIdentity


ROOT = Path(__file__).resolve().parents[1]
SCENARIO_ROOT = ROOT / "evaluation" / "scenarios" / "projectodyssey"
FIXTURE_ROOT = ROOT / "fixtures" / "project-h-projectodyssey-jit"
DEEPAGENTS_SCENARIO_ROOT = ROOT / "evaluation" / "scenarios" / "deepagents"
DEEPAGENTS_FIXTURE_ROOT = ROOT / "fixtures" / "project-i-deepagents-package"
GRAPHITI_SCENARIO_ROOT = ROOT / "evaluation" / "scenarios" / "graphiti"
GRAPHITI_FIXTURE_ROOT = ROOT / "fixtures" / "project-j-graphiti-backend"
VARIANTS = [
    "raw_full_history",
    "semantic_rerank",
    "recency_aware",
    "recall_time_resolver",
    "recallpack",
]


def _isolated_result(
    *,
    variant_id: str,
    generated_files: list[dict[str, str]],
    full_suite_passed: bool,
) -> IsolatedSuiteResult:
    hidden_status = "passed" if full_suite_passed else "failed"
    tests = [
        {
            "name": "network_probe",
            "status": "passed",
            "duration_ms": 1,
            "evidence_artifact_id": "runner_result_json",
        },
        {
            "name": "tests.test_policy.PolicyTests.test_policy",
            "status": hidden_status,
            "duration_ms": 2,
            "evidence_artifact_id": "runner_result_json",
        },
    ]
    payload = {
        "tests": tests,
        "full_suite_passed": full_suite_passed,
        "passed": 2 if full_suite_passed else 1,
        "failed": 0 if full_suite_passed else 1,
        "exit_code": 0 if full_suite_passed else 1,
        "timed_out": False,
    }
    stdout = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    binding = isolation_module.IsolatedExecutionBinding(
        variant_id=variant_id,
        patch_sha256=docker_module.canonical_generated_files_sha256(generated_files),
        repository_tree_sha256="a" * 64,
        hidden_test_tree_sha256="b" * 64,
        execution_nonce=f"nonce-{variant_id}",
        docker_argv_sha256="c" * 64,
        authority_mode="test_only_injected_runner",
    )
    return IsolatedSuiteResult(
        exit_code=payload["exit_code"],
        stdout=stdout,
        stderr="",
        json_result=payload,
        blocked=False,
        timed_out=False,
        failure_code=None,
        host_fallback_used=False,
        execution_binding=binding,
    )


class V4VariantExecutionTests(unittest.TestCase):
    def test_production_patch_rejection_requires_complete_execution_identity(self):
        manifest = {"record_type": "execution_manifest_probe"}
        slot = {"scenario_slot": "projectodyssey", "slot_index": 1}

        with self.assertRaisesRegex(
            ValueError,
            "production execution binding does not match",
        ):
            _validate_runner_execution_identity(
                {
                    "execution_binding": {
                        "authority_mode": "patch_not_executed",
                        "execution_manifest_sha256": None,
                        "scenario_id": None,
                        "slot_index": None,
                        "attempt_no": None,
                    }
                },
                manifest=manifest,
                slot=slot,
                attempt_no=1,
            )

        _validate_runner_execution_identity(
            {
                "execution_binding": {
                    "authority_mode": "test_only_patch_not_executed",
                    "execution_manifest_sha256": None,
                    "scenario_id": None,
                    "slot_index": None,
                    "attempt_no": None,
                }
            },
            manifest=manifest,
            slot=slot,
            attempt_no=1,
        )

    def test_diagnostic_result_adapts_to_closed_runner_outputs_without_fake_final_claim(self):
        result = execute_v4_diagnostic_variants(
            scenario_root=SCENARIO_ROOT,
            fixture_root=FIXTURE_ROOT,
        )
        contract = build_runtime_evaluator_contract(
            platform="linux/amd64",
            image_digest="sha256:" + "1" * 64,
            base_image_digest="sha256:" + "2" * 64,
        )
        isolated = {
            variant_id: _isolated_result(
                variant_id=variant_id,
                generated_files=result.variants[variant_id].generated_files,
                full_suite_passed=variant_id
                in {"recency_aware", "recall_time_resolver", "recallpack"}
            )
            for variant_id in result.variants
        }
        outputs = build_v4_diagnostic_runner_outputs(
            result,
            fixture_root=FIXTURE_ROOT,
            isolated_results=isolated,
            evaluator_contract=contract,
        )

        self.assertEqual(set(outputs), set(VARIANTS))
        for variant_id, output in outputs.items():
            with self.subTest(variant_id=variant_id):
                variant = result.variants[variant_id]
                self.assertEqual(output["context_text"], variant.model_visible_context)
                self.assertEqual(
                    output["context_sha256"], variant.model_visible_context_sha256
                )
                self.assertEqual(output["exact_token_count"], variant.exact_token_count)
                self.assertEqual(
                    output["selected_sources"],
                    list(variant.selected_source_refs),
                )
                self.assertEqual(output["patch_diff"], variant.downstream["patch_diff"])
                self.assertEqual(output["patched_files"], variant.generated_files)
                self.assertEqual(
                    output["sandbox"], sandbox_evidence_from_contract(contract)
                )
                self.assertEqual(
                    output["test_result"], isolated[variant_id].json_result
                )
                self.assertEqual(output["stdout"], isolated[variant_id].stdout)
                self.assertEqual(
                    output["runtime_trace"]["evidence_status"],
                    "diagnostic_isolated_runner_complete",
                )
                self.assertEqual(
                    output["attempt_outcome"]["status"],
                    "completed" if output["full_suite_passed"] else "adverse",
                )
                self.assertIsNone(output["failure"])
                self.assertNotIn("claim_status", output["runtime_trace"])
                self.assertEqual(
                    {item["path"] for item in output["original_files"]},
                    {item["path"] for item in output["patched_files"]},
                )

        swapped = dict(isolated)
        swapped["raw_full_history"], swapped["recallpack"] = (
            swapped["recallpack"],
            swapped["raw_full_history"],
        )
        with self.assertRaisesRegex(ValueError, "variant binding"):
            build_v4_diagnostic_runner_outputs(
                result,
                fixture_root=FIXTURE_ROOT,
                isolated_results=swapped,
                evaluator_contract=contract,
            )

    def test_adapter_retains_rejected_patch_and_sandbox_failure_attempts(self):
        result = execute_v4_diagnostic_variants(
            scenario_root=SCENARIO_ROOT,
            fixture_root=FIXTURE_ROOT,
        )
        rejected_variant = replace(
            result.variants["semantic_rerank"],
            generated_files=[],
            downstream={
                **result.variants["semantic_rerank"].downstream,
                "accepted": False,
                "error": "empty_patch",
                "patch_diff": "",
                "test_status": "not_run_patch_rejected",
            },
        )
        result = replace(
            result,
            variants={**result.variants, "semantic_rerank": rejected_variant},
        )
        contract = build_runtime_evaluator_contract(
            platform="linux/amd64",
            image_digest="sha256:" + "1" * 64,
            base_image_digest="sha256:" + "2" * 64,
        )
        isolated = {
            variant_id: _isolated_result(
                variant_id=variant_id,
                generated_files=variant.generated_files,
                full_suite_passed=True,
            )
            for variant_id, variant in result.variants.items()
        }
        isolated["semantic_rerank"] = replace(
            isolated["semantic_rerank"],
            exit_code=None,
            stdout="",
            json_result=None,
            blocked=True,
            failure_code="empty_patch",
            execution_binding=replace(
                isolated["semantic_rerank"].execution_binding,
                authority_mode="test_only_patch_not_executed",
            ),
        )
        isolated["raw_full_history"] = replace(
            isolated["raw_full_history"],
            exit_code=None,
            stdout="",
            stderr="timeout",
            json_result=None,
            blocked=True,
            timed_out=True,
            failure_code="sandbox_timeout",
            container_name="recallpack-eval-timeout-test",
            cleanup_attempted=True,
            cleanup_succeeded=True,
        )

        outputs = build_v4_diagnostic_runner_outputs(
            result,
            fixture_root=FIXTURE_ROOT,
            isolated_results=isolated,
            evaluator_contract=contract,
        )

        rejected = outputs["semantic_rerank"]
        self.assertEqual(
            rejected["attempt_outcome"],
            {
                "status": "adverse",
                "stage": "patch_generation",
                "code": "empty_patch",
            },
        )
        self.assertIsNone(rejected["test_result"])
        self.assertEqual(rejected["patched_files"], [])
        timeout = outputs["raw_full_history"]
        self.assertEqual(
            timeout["attempt_outcome"],
            {
                "status": "invalidated",
                "stage": "sandbox",
                "code": "technical_failure",
            },
        )
        self.assertEqual(timeout["failure"]["code"], "sandbox_timeout")
        self.assertIsNone(timeout["test_result"])
        self.assertEqual(
            timeout["runtime_trace"]["sandbox_cleanup"],
            {
                "container_name": "recallpack-eval-timeout-test",
                "attempted": True,
                "succeeded": True,
            },
        )

        stale_patch_identity = dict(isolated)
        stale_patch_identity["semantic_rerank"] = replace(
            isolated["semantic_rerank"],
            execution_binding=replace(
                isolated["semantic_rerank"].execution_binding,
                execution_manifest_sha256="f" * 64,
                scenario_id=result.scenario_id,
                slot_index=1,
                attempt_no=1,
            ),
        )
        with self.assertRaisesRegex(ValueError, "execution identity mismatch"):
            build_v4_diagnostic_runner_outputs(
                result,
                fixture_root=FIXTURE_ROOT,
                isolated_results=stale_patch_identity,
                evaluator_contract=contract,
            )

        production_identity = ProductionExecutionIdentity(
            execution_manifest_sha256="a" * 64,
            scenario_id=result.scenario_id,
            slot_index=1,
            attempt_no=1,
            repository_snapshot_sha256="d" * 64,
            hidden_test_tree_sha256="e" * 64,
        )
        rejected_only = replace(
            result,
            variants={"semantic_rerank": rejected_variant},
        )
        missing_patch_identity = {
            "semantic_rerank": replace(
                isolated["semantic_rerank"],
                execution_binding=replace(
                    isolated["semantic_rerank"].execution_binding,
                    authority_mode="test_only_patch_not_executed",
                    execution_manifest_sha256=None,
                    scenario_id=None,
                    slot_index=None,
                    attempt_no=None,
                ),
            )
        }
        with self.assertRaisesRegex(ValueError, "execution identity mismatch"):
            build_v4_diagnostic_runner_outputs(
                rejected_only,
                fixture_root=FIXTURE_ROOT,
                isolated_results=missing_patch_identity,
                evaluator_contract=contract,
                production_execution_identities={
                    "semantic_rerank": production_identity,
                },
            )

        production_patch_identity = {
            "semantic_rerank": replace(
                missing_patch_identity["semantic_rerank"],
                execution_binding=replace(
                    missing_patch_identity["semantic_rerank"].execution_binding,
                    repository_tree_sha256=(
                        production_identity.repository_snapshot_sha256
                    ),
                    hidden_test_tree_sha256=production_identity.hidden_test_tree_sha256,
                    authority_mode="patch_not_executed",
                    execution_manifest_sha256=(
                        production_identity.execution_manifest_sha256
                    ),
                    scenario_id=production_identity.scenario_id,
                    slot_index=production_identity.slot_index,
                    attempt_no=production_identity.attempt_no,
                    repository_snapshot_sha256=(
                        production_identity.repository_snapshot_sha256
                    ),
                    frozen_hidden_test_tree_sha256=(
                        production_identity.hidden_test_tree_sha256
                    ),
                ),
            )
        }
        with self.assertRaisesRegex(ValueError, "production execution receipt"):
            build_v4_diagnostic_runner_outputs(
                rejected_only,
                fixture_root=FIXTURE_ROOT,
                isolated_results=production_patch_identity,
                evaluator_contract=contract,
                production_execution_identities={
                    "semantic_rerank": production_identity,
                },
            )

        test_only_patch_identity = {
            "semantic_rerank": replace(
                missing_patch_identity["semantic_rerank"],
                execution_binding=replace(
                    missing_patch_identity["semantic_rerank"].execution_binding,
                    authority_mode="test_only_injected_runner",
                    execution_manifest_sha256=(
                        production_identity.execution_manifest_sha256
                    ),
                    scenario_id=production_identity.scenario_id,
                    slot_index=production_identity.slot_index,
                    attempt_no=production_identity.attempt_no,
                    repository_snapshot_sha256=(
                        production_identity.repository_snapshot_sha256
                    ),
                    frozen_hidden_test_tree_sha256=(
                        production_identity.hidden_test_tree_sha256
                    ),
                ),
            )
        }
        with self.assertRaisesRegex(ValueError, "execution authority mismatch"):
            build_v4_diagnostic_runner_outputs(
                rejected_only,
                fixture_root=FIXTURE_ROOT,
                isolated_results=test_only_patch_identity,
                evaluator_contract=contract,
                production_execution_identities={
                    "semantic_rerank": production_identity,
                },
            )

    def test_diagnostic_patch_provider_uses_context_policy_not_fixture_phrase_pair(self):
        provider = DeterministicPolicyPatchProvider()
        result = provider.generate_patch(
            PatchGenerationRequest(
                goal="Update JIT crash handling for CI.",
                selected_context=[
                    {
                        "text": (
                            "Compiler crashes must be investigated forward. Retries, "
                            "skips, and continue-on-error are prohibited; attach the "
                            "smallest failing case."
                        )
                    }
                ],
                allowed_paths=["src/ci_policy.py"],
                source_files=[
                    {
                        "path": "src/ci_policy.py",
                        "content": (
                            "def handle_jit_crash(error_message):\n"
                            "    return {\n"
                            "        \"action\": \"inspect\",\n"
                            "        \"retry\": False,\n"
                            "        \"retry_attempts\": 0,\n"
                            "        \"continue_on_error\": False,\n"
                            "        \"skip\": False,\n"
                            "        \"minimal_reproducer_required\": False,\n"
                            "    }\n"
                        ),
                    }
                ],
            )
        )

        self.assertFalse(result.used_gold_patch_variants)
        self.assertIn("'retry': False", result.files[0]["content"])
        self.assertIn("'minimal_reproducer_required': True", result.files[0]["content"])
        self.assertEqual(
            result.trace.usage["generation_mode"],
            "deterministic_ast_policy_transform",
        )
        paraphrased = provider.generate_patch(
            PatchGenerationRequest(
                goal="Update JIT crash handling for CI.",
                selected_context=[
                    {
                        "text": (
                            "For CI compiler crashes, disable every retry attempt, "
                            "fail immediately, and require a compact crash reproducer."
                        )
                    }
                ],
                allowed_paths=["src/ci_policy.py"],
                source_files=[
                    {
                        "path": "src/ci_policy.py",
                        "content": result.files[0]["content"].replace(
                            "'minimal_reproducer_required': True",
                            "'minimal_reproducer_required': False",
                        ),
                    }
                ],
            )
        )
        self.assertEqual(len(paraphrased.files), 1)
        self.assertIn("'minimal_reproducer_required': True", paraphrased.files[0]["content"])

        decoy_source = (
            "DECOY = {\n"
            "    'action': 'leave_me', 'retry': True, 'retry_attempts': 9,\n"
            "    'continue_on_error': True, 'skip': True,\n"
            "    'minimal_reproducer_required': False,\n"
            "}\n\n"
            + result.files[0]["content"].replace(
                "'minimal_reproducer_required': True",
                "'minimal_reproducer_required': False",
            )
        )
        decoy_result = provider.generate_patch(
            PatchGenerationRequest(
                goal="Update JIT crash handling for CI.",
                selected_context=[
                    {
                        "text": (
                            "Disable retries for compiler crashes and require a "
                            "minimal reproducer."
                        )
                    }
                ],
                allowed_paths=["src/ci_policy.py"],
                source_files=[{"path": "src/ci_policy.py", "content": decoy_source}],
            )
        )
        self.assertIn("'action': 'leave_me'", decoy_result.files[0]["content"])
        self.assertIn("'minimal_reproducer_required': True", decoy_result.files[0]["content"])

        local_decoy_source = (
            "def handle_jit_crash(error_message):\n"
            "    decoy = {\n"
            "        'action': 'leave_me', 'retry': True, 'retry_attempts': 9,\n"
            "        'continue_on_error': True, 'skip': True,\n"
            "        'minimal_reproducer_required': False,\n"
            "    }\n"
            "    return {\n"
            "        'action': 'inspect', 'retry': False, 'retry_attempts': 0,\n"
            "        'continue_on_error': False, 'skip': False,\n"
            "        'minimal_reproducer_required': False,\n"
            "    }\n"
        )
        local_decoy_result = provider.generate_patch(
            PatchGenerationRequest(
                goal="Update JIT crash handling for CI.",
                selected_context=[
                    {
                        "text": (
                            "Disable retries for compiler crashes and require a "
                            "minimal reproducer."
                        )
                    }
                ],
                allowed_paths=["src/ci_policy.py"],
                source_files=[
                    {"path": "src/ci_policy.py", "content": local_decoy_source}
                ],
            )
        )
        self.assertIn("'action': 'leave_me'", local_decoy_result.files[0]["content"])
        self.assertIn("'retry_attempts': 9", local_decoy_result.files[0]["content"])
        self.assertIn(
            "'minimal_reproducer_required': True",
            local_decoy_result.files[0]["content"],
        )

    def test_five_variants_execute_without_gold_or_relation_labels_in_model_context(self):
        with patch(
            "recallpack.downstream._run_hidden_tests_safely",
            side_effect=AssertionError("V4 must not run hidden tests on the host"),
        ):
            result = execute_v4_diagnostic_variants(
                scenario_root=SCENARIO_ROOT,
                fixture_root=FIXTURE_ROOT,
            )

        self.assertEqual(result.scenario_id, "projectodyssey")
        self.assertEqual(list(result.variants), VARIANTS)
        self.assertEqual(
            list(result.variants["raw_full_history"].selected_source_refs),
            [f"projectodyssey:turn-00{index}" for index in range(1, 4)],
        )
        self.assertEqual(result.evidence_status, "diagnostic_pending_independent_review")
        self.assertEqual(
            set(result.evidence_bindings),
            {
                "source_ledger",
                "relation_label_ledger",
                "provenance",
                "leakage_review",
                "scenario_packet",
            },
        )
        expected_inputs = [
            "projectodyssey:turn-001",
            "projectodyssey:turn-002",
            "projectodyssey:turn-003",
        ]
        self.assertTrue(
            all(
                variant.execution_trace["input_source_refs"] == expected_inputs
                for variant in result.variants.values()
            )
        )

        for variant_id in VARIANTS:
            with self.subTest(variant_id=variant_id):
                variant = result.variants[variant_id]
                self.assertEqual(
                    variant.model_visible_context_sha256,
                    hashlib.sha256(
                        variant.model_visible_context.encode("utf-8")
                    ).hexdigest(),
                )
                self.assertEqual(
                    variant.exact_token_count,
                    count_canonical_json_tokens(variant.model_visible_context),
                )
                if variant_id == "raw_full_history":
                    self.assertFalse(variant.budget_comparable)
                else:
                    self.assertTrue(variant.budget_comparable)
                    self.assertLessEqual(variant.exact_token_count, 512)
                    self.assertLessEqual(len(variant.selected_context), 3)
                model_visible = json.dumps(variant.selected_context).lower()
                self.assertNotIn("lifecycle_role", model_visible)
                self.assertNotIn("relation_kind", model_visible)
                self.assertNotIn("required_sources", model_visible)
                self.assertNotIn("stale_sources", model_visible)
                self.assertNotIn("hidden_test", model_visible)
                self.assertNotIn("projectodyssey:turn-004", model_visible)
                self.assertNotIn('"source_ref"', model_visible)
                self.assertNotIn('"id"', model_visible)
                for source_ref in expected_inputs:
                    self.assertNotIn(source_ref, model_visible)
                self.assertFalse(
                    variant.downstream["patch_generation"]["used_gold_patch_variants"]
                )
                self.assertEqual(
                    variant.downstream["patch_generation"]["generation_mode"],
                    "deterministic_ast_policy_transform",
                )

        semantic_sources = set(
            result.variants["semantic_rerank"].selected_source_refs
        )
        resolver_sources = set(
            result.variants["recall_time_resolver"].selected_source_refs
        )
        recallpack_sources = set(result.variants["recallpack"].selected_source_refs)
        self.assertIn("projectodyssey:turn-001", semantic_sources)
        self.assertEqual(len(semantic_sources), 3)
        self.assertEqual(
            result.variants["recency_aware"].selected_source_refs[0],
            "projectodyssey:turn-003",
        )
        self.assertIn("projectodyssey:turn-002", resolver_sources)
        self.assertNotIn("projectodyssey:turn-001", resolver_sources)
        self.assertEqual(
            recallpack_sources,
            {"projectodyssey:turn-002", "projectodyssey:turn-003"},
        )

        expected_roles = {
            "raw_full_history": {"patch_generation"},
            "semantic_rerank": {"embedding", "rerank", "patch_generation"},
            "recency_aware": {"embedding", "rerank", "patch_generation"},
            "recall_time_resolver": {
                "memory_decision",
                "embedding",
                "rerank",
                "patch_generation",
            },
            "recallpack": {
                "memory_decision",
                "embedding",
                "rerank",
                "patch_generation",
            },
        }
        for variant_id, roles in expected_roles.items():
            self.assertEqual(
                {trace["role"] for trace in result.variants[variant_id].provider_traces},
                roles,
            )

        self.assertTrue(
            all(
                variant.downstream["execution_mode"] == "patch_generation_only"
                and variant.downstream["test_status"] == "pending_isolated_runner"
                and "summary" not in variant.downstream
                for variant in result.variants.values()
            )
        )
        self.assertEqual(
            result.classification,
            "diagnostic_patch_generation_only",
        )
        self.assertIsNone(result.strongest_baseline_full_suite_passed)
        self.assertIsNone(result.recallpack_full_suite_passed)
        self.assertIn(
            "authored source-backed scenario",
            " ".join(result.limitations).lower(),
        )

    def test_strongest_baseline_uses_full_suite_outcomes_and_reports_ties(self):
        variants = {
            "semantic_rerank": SimpleNamespace(
                downstream={"summary": {"passed": 2, "failed": 1}}
            ),
            "recency_aware": SimpleNamespace(
                downstream={"summary": {"passed": 1, "failed": 2}}
            ),
            "recall_time_resolver": SimpleNamespace(
                downstream={"summary": {"passed": 0, "failed": 3}}
            ),
        }

        self.assertEqual(
            variant_module._select_strongest_baseline_ids(variants),
            ("semantic_rerank", "recency_aware", "recall_time_resolver"),
        )

    def test_scenario_packet_rejects_malformed_relation_ledger_shape(self):
        mutations = (
            (
                "relation-label-ledger.json",
                lambda payload: payload.update(entries="not-a-ledger"),
            ),
            (
                "relation-label-ledger.json",
                lambda payload: payload["entries"][1].update(
                    opportunity_id=payload["entries"][0]["opportunity_id"]
                ),
            ),
            (
                "leakage-review.json",
                lambda payload: payload["checks"].update(
                    hidden_test_text_model_visible=True,
                    relation_labels_model_visible=True,
                ),
            ),
            (
                "provenance.json",
                lambda payload: payload.update(unreviewed_extra=True),
            ),
        )
        for filename, mutate in mutations:
            with self.subTest(filename=filename, mutation=repr(mutate)):
                with tempfile.TemporaryDirectory() as tmpdir:
                    scenario_copy = Path(tmpdir) / "scenario"
                    shutil.copytree(SCENARIO_ROOT, scenario_copy)
                    target_path = scenario_copy / filename
                    payload = json.loads(target_path.read_text())
                    mutate(payload)
                    target_path.write_text(json.dumps(payload))

                    with self.assertRaisesRegex(ValueError, "invalid_run_reference"):
                        execute_v4_diagnostic_variants(
                            scenario_root=scenario_copy,
                            fixture_root=FIXTURE_ROOT,
                        )

    def test_deepagents_and_graphiti_execute_real_lifecycle_and_downstream_proof(self):
        scenarios = (
            (
                DEEPAGENTS_SCENARIO_ROOT,
                DEEPAGENTS_FIXTURE_ROOT,
                "deepagents",
                "src/package_policy.py",
            ),
            (
                GRAPHITI_SCENARIO_ROOT,
                GRAPHITI_FIXTURE_ROOT,
                "graphiti",
                "src/backend_policy.py",
            ),
        )
        for scenario_root, fixture_root, scenario_id, expected_path in scenarios:
            with self.subTest(scenario_id=scenario_id):
                result = execute_v4_diagnostic_variants(
                    scenario_root=scenario_root,
                    fixture_root=fixture_root,
                )
                recallpack = result.variants["recallpack"]
                memory_traces = [
                    trace
                    for trace in recallpack.provider_traces
                    if trace["role"] == "memory_decision"
                ]
                self.assertEqual(result.scenario_id, scenario_id)
                self.assertTrue(memory_traces)
                self.assertEqual(
                    [
                        item["operation"]
                        for item in recallpack.execution_trace["observations"]
                    ],
                    ["write", "write", "write"],
                )
                self.assertEqual(
                    recallpack.downstream["test_status"],
                    "pending_isolated_runner",
                )
                self.assertEqual(recallpack.generated_files[0]["path"], expected_path)


if __name__ == "__main__":
    unittest.main()
