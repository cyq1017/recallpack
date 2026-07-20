from __future__ import annotations

import copy
import hashlib
from pathlib import Path, PurePosixPath
from typing import Any, Mapping

from recallpack.evaluation_docker import (
    canonical_generated_files_sha256,
    sandbox_evidence_from_contract,
    validate_isolated_result,
    validate_retained_technical_failure,
)
from recallpack.evaluation_variants import V4DiagnosticScenarioResult
from recallpack.isolation import (
    IsolatedSuiteResult,
    ProductionExecutionIdentity,
    execution_binding_matches_identity,
    has_valid_production_execution_receipt,
)


def build_v4_diagnostic_runner_outputs(
    result: V4DiagnosticScenarioResult,
    *,
    fixture_root: str | Path,
    isolated_results: Mapping[str, IsolatedSuiteResult],
    evaluator_contract: Mapping[str, Any],
    production_execution_identities: Mapping[
        str, ProductionExecutionIdentity
    ] | None = None,
) -> dict[str, dict[str, Any]]:
    """Convert executed diagnostics into runner envelopes without activating claims."""
    root = Path(fixture_root)
    repo_root = (root / "repo_snapshot").resolve()
    if set(isolated_results) != set(result.variants):
        raise ValueError("invalid_sandbox_evidence: isolated result grid is incomplete")
    production_mode = production_execution_identities is not None
    if production_mode and set(production_execution_identities) != set(
        result.variants
    ):
        raise ValueError(
            "invalid_sandbox_evidence: production execution identities are required"
        )
    sandbox_evidence = sandbox_evidence_from_contract(evaluator_contract)
    outputs: dict[str, dict[str, Any]] = {}
    for variant_id, variant in result.variants.items():
        downstream = variant.downstream
        patch_diff = downstream.get("patch_diff")
        isolated = isolated_results[variant_id]
        binding = isolated.execution_binding
        expected_identity = (
            production_execution_identities.get(variant_id)
            if production_execution_identities is not None
            else None
        )
        if (
            binding is None
            or binding.variant_id != variant_id
            or binding.patch_sha256
            != canonical_generated_files_sha256(variant.generated_files)
        ):
            raise ValueError(
                "invalid_sandbox_evidence: isolated result variant binding mismatch"
            )
        patch_accepted = (
            downstream.get("accepted") is True
            and isinstance(patch_diff, str)
            and bool(patch_diff)
            and bool(variant.generated_files)
        )
        binding_has_production_identity = any(
            value is not None
            for value in (
                binding.execution_manifest_sha256,
                binding.scenario_id,
                binding.slot_index,
                binding.attempt_no,
            )
        )
        if production_mode:
            if (
                type(expected_identity) is not ProductionExecutionIdentity
                or expected_identity.scenario_id != result.scenario_id
                or not execution_binding_matches_identity(binding, expected_identity)
            ):
                raise ValueError(
                    "invalid_sandbox_evidence: isolated result execution identity mismatch"
                )
            expected_authority_mode = (
                "production_docker" if patch_accepted else "patch_not_executed"
            )
            if binding.authority_mode != expected_authority_mode:
                raise ValueError(
                    "invalid_sandbox_evidence: isolated result execution authority mismatch"
                )
            if not has_valid_production_execution_receipt(
                isolated,
                expected_identity=expected_identity,
            ):
                raise ValueError(
                    "invalid_sandbox_evidence: production execution receipt is invalid"
                )
        else:
            expected_authority_mode = (
                "test_only_injected_runner"
                if patch_accepted
                else "test_only_patch_not_executed"
            )
            if binding.authority_mode != expected_authority_mode:
                raise ValueError(
                    "invalid_sandbox_evidence: isolated result execution authority mismatch"
                )
            if binding_has_production_identity:
                raise ValueError(
                    "invalid_sandbox_evidence: isolated result execution identity mismatch"
                )
        original_files = (
            [
                {
                    "path": generated["path"],
                    "content": _read_original_file(repo_root, generated["path"]),
                }
                for generated in variant.generated_files
            ]
            if patch_accepted
            else []
        )
        test_result: dict[str, Any] | None = None
        full_suite_passed: bool | None = None
        failure: dict[str, Any] | None = None
        if not patch_accepted:
            error = str(downstream.get("error") or "patch_rejected")
            if not isolated.blocked or isolated.failure_code != error:
                raise ValueError(
                    "invalid_run_reference: rejected patch attempt binding mismatch"
                )
            attempt_outcome = {
                "status": "adverse",
                "stage": "patch_generation",
                "code": "empty_patch" if error == "empty_patch" else "patch_rejected",
            }
            evidence_status = "diagnostic_patch_rejected_retained"
        elif isolated.blocked:
            validate_retained_technical_failure(
                isolated,
                expected_identity=expected_identity,
            )
            attempt_outcome = {
                "status": "invalidated",
                "stage": "sandbox",
                "code": "technical_failure",
            }
            failure = {
                "code": isolated.failure_code,
                "detail": (
                    "isolated evaluator did not produce a closed test result; "
                    f"cleanup_attempted={isolated.cleanup_attempted}; "
                    f"cleanup_succeeded={isolated.cleanup_succeeded}"
                ),
                "evidence_sha256": hashlib.sha256(
                    (isolated.stdout + "\n" + isolated.stderr).encode("utf-8")
                ).hexdigest(),
            }
            evidence_status = "diagnostic_sandbox_failure_retained"
        else:
            validate_isolated_result(
                isolated,
                expected_identity=expected_identity,
            )
            test_result = copy.deepcopy(isolated.json_result)
            if not isinstance(test_result, dict):
                raise ValueError("invalid_sandbox_evidence: isolated test result is missing")
            full_suite_passed = test_result["full_suite_passed"]
            attempt_outcome = (
                {"status": "completed", "stage": "complete", "code": "success"}
                if full_suite_passed
                else {
                    "status": "adverse",
                    "stage": "hidden_test",
                    "code": "hidden_tests_failed",
                }
            )
            evidence_status = "diagnostic_isolated_runner_complete"
        runtime_trace = copy.deepcopy(variant.execution_trace)
        runtime_trace.update(
            {
                "scenario_id": result.scenario_id,
                "variant_id": variant_id,
                "evidence_status": evidence_status,
                "classification": result.classification,
                "execution_binding": {
                    "variant_id": binding.variant_id,
                    "patch_sha256": binding.patch_sha256,
                    "repository_tree_sha256": binding.repository_tree_sha256,
                    "hidden_test_tree_sha256": binding.hidden_test_tree_sha256,
                    "execution_nonce": binding.execution_nonce,
                    "docker_argv_sha256": binding.docker_argv_sha256,
                    "authority_mode": binding.authority_mode,
                    "execution_manifest_sha256": (
                        binding.execution_manifest_sha256
                    ),
                    "scenario_id": binding.scenario_id,
                    "slot_index": binding.slot_index,
                    "attempt_no": binding.attempt_no,
                    "repository_snapshot_sha256": (
                        binding.repository_snapshot_sha256
                    ),
                    "frozen_hidden_test_tree_sha256": (
                        binding.frozen_hidden_test_tree_sha256
                    ),
                },
                "sandbox_cleanup": {
                    "container_name": isolated.container_name,
                    "attempted": isolated.cleanup_attempted,
                    "succeeded": isolated.cleanup_succeeded,
                },
            }
        )
        context_bytes = variant.model_visible_context.encode("utf-8")
        model_latency_ms = _provider_latency_ms(variant.provider_traces)
        sandbox_latency_ms = _sandbox_duration_ms(test_result) if test_result else 0
        outputs[variant_id] = {
            "run_id": _run_id(result.scenario_id, variant_id),
            "variant_id": variant_id,
            "full_suite_passed": full_suite_passed,
            "stdout": isolated.stdout,
            "stderr": isolated.stderr,
            "context_text": variant.model_visible_context,
            "context_sha256": variant.model_visible_context_sha256,
            "context_bytes": len(context_bytes),
            "exact_token_count": variant.exact_token_count,
            "selected_sources": list(variant.selected_source_refs),
            "runtime_trace": runtime_trace,
            "patch_diff": patch_diff if patch_accepted else "",
            "original_files": original_files,
            "patched_files": (
                copy.deepcopy(variant.generated_files) if patch_accepted else []
            ),
            "test_result": test_result,
            "sandbox": copy.deepcopy(sandbox_evidence),
            "provider_traces": copy.deepcopy(variant.provider_traces),
            "latency_ms": {
                "total": model_latency_ms + sandbox_latency_ms,
                "stages": {
                    "model": model_latency_ms,
                    "sandbox": sandbox_latency_ms,
                },
            },
            "attempt_outcome": attempt_outcome,
            "failure": failure,
        }
    return outputs


def _read_original_file(repo_root: Path, relative_path: Any) -> str:
    if not isinstance(relative_path, str):
        raise ValueError("invalid_patch_result: generated path must be text")
    path = PurePosixPath(relative_path)
    if path.is_absolute() or "." in path.parts or ".." in path.parts:
        raise ValueError("invalid_patch_result: generated path escaped fixture root")
    resolved = (repo_root / path.as_posix()).resolve()
    if resolved == repo_root or repo_root not in resolved.parents or not resolved.is_file():
        raise ValueError("invalid_patch_result: original file is unavailable")
    return resolved.read_text()


def _sandbox_duration_ms(test_result: Mapping[str, Any]) -> int:
    tests = test_result.get("tests")
    if not isinstance(tests, list):
        raise ValueError("invalid_test_result: isolated tests are malformed")
    durations = [
        item.get("duration_ms")
        for item in tests
        if isinstance(item, Mapping)
    ]
    if len(durations) != len(tests) or any(
        not isinstance(value, int) or isinstance(value, bool) or value < 0
        for value in durations
    ):
        raise ValueError("invalid_test_result: isolated durations are malformed")
    return sum(durations)


def _provider_latency_ms(provider_traces: list[dict[str, Any]]) -> int:
    total = 0
    for trace in provider_traces:
        if not isinstance(trace, Mapping):
            raise ValueError("invalid_provider_trace: trace must be an object")
        latency_ms = trace.get("latency_ms", 0)
        if type(latency_ms) is not int or latency_ms < 0:
            raise ValueError("invalid_provider_trace: latency_ms is invalid")
        total += latency_ms
    return total


def _run_id(scenario_id: str, variant_id: str) -> str:
    compact = "".join(
        character for character in f"{scenario_id}_{variant_id}" if character.isalnum()
    )
    if not compact:
        raise ValueError("invalid_run_reference: run identity is empty")
    return f"eval_{compact}"
