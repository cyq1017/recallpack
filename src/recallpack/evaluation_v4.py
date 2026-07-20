from __future__ import annotations

import hashlib
import re
from typing import Any, Mapping, Sequence

from recallpack.budget import canonical_json
from recallpack.evidence_common import _sha256_hex


V4_VARIANTS = (
    "raw_full_history",
    "semantic_rerank",
    "recency_aware",
    "recall_time_resolver",
    "recallpack",
)
_COMPARATORS = V4_VARIANTS[1:4]
_WRITABLE_PATHS = (
    "src/retry.py",
    "src/retry_policy.py",
    "src/auth.py",
    "src/config_loader.py",
    "pyproject.toml",
)
_SHARED_INPUT_FIELDS = (
    "repository_snapshot_artifact_id",
    "model_visible_snapshot_artifact_id",
    "prompt_template_artifact_id",
    "patch_provider_contract_artifact_id",
    "runner_contract_artifact_id",
)
_SHARED_INPUT_KINDS = {
    "repository_snapshot_artifact_id": "repository_snapshot",
    "model_visible_snapshot_artifact_id": "model_visible_snapshot",
    "prompt_template_artifact_id": "prompt_template",
    "patch_provider_contract_artifact_id": "patch_provider_contract",
    "runner_contract_artifact_id": "runner_contract",
}
_SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")


def validate_v4_comparison_contract(
    manifest: Mapping[str, Any],
    *,
    artifact_bytes: Mapping[str, bytes],
) -> dict[str, Any]:
    variants = manifest.get("variants")
    if variants != list(V4_VARIANTS):
        _fail("invalid_rung_grid", "variants must equal the frozen five-variant order")
    comparison = manifest.get("comparison_contract")
    if not isinstance(comparison, Mapping):
        _fail("unequal_comparison_contract", "comparison_contract must be present")

    expected = {
        "budget_tokens": 512,
        "hidden_test_visibility": "after_model_output_fixed",
        "budget_scope": "budget_comparable_variants_only",
        "variant_input_policy": "identical_across_budget_comparable_variants",
        "writable_paths": list(_WRITABLE_PATHS),
    }
    for field, value in expected.items():
        if comparison.get(field) != value:
            _fail(
                "unequal_comparison_contract",
                f"comparison_contract {field} must equal the frozen value",
            )

    tokenizer = comparison.get("tokenizer")
    if tokenizer != {
        "encoding": "o200k_base",
        "package": "tiktoken",
        "package_version": "0.13.0",
        "exact": True,
    }:
        _fail("unequal_comparison_contract", "tokenizer contract must be exact")

    comparability = comparison.get("variant_comparability")
    if not isinstance(comparability, Mapping) or set(comparability) != set(V4_VARIANTS):
        _fail("unequal_comparison_contract", "variant comparability set is incomplete")
    if any(not isinstance(comparability[variant], Mapping) for variant in V4_VARIANTS):
        _fail("unequal_comparison_contract", "variant comparability entries must be objects")
    comparable = [
        variant
        for variant in V4_VARIANTS
        if comparability[variant].get("budget_comparable") is True
    ]
    if comparable != list(V4_VARIANTS[1:]):
        _fail("unequal_comparison_contract", "budget-comparable variants must be fixed")
    eligible = [
        variant
        for variant in V4_VARIANTS
        if comparability[variant].get("headline_comparator_eligible") is True
    ]
    if eligible != list(_COMPARATORS):
        _fail("unequal_comparison_contract", "SC-005 comparator set must be fixed")

    shared = {field: comparison.get(field) for field in _SHARED_INPUT_FIELDS}
    if any(not isinstance(value, str) for value in shared.values()) or len(
        set(shared.values())
    ) != len(shared):
        _fail(
            "invalid_artifact_reference",
            "shared input artifact IDs must be present and distinct",
        )

    catalog = manifest.get("input_artifact_catalog")
    if not isinstance(catalog, Mapping):
        _fail("invalid_artifact_reference", "input artifact catalog must be an object")
    for field, artifact_id in shared.items():
        metadata = catalog.get(artifact_id)
        payload = artifact_bytes.get(artifact_id)
        if (
            not isinstance(metadata, Mapping)
            or not isinstance(payload, (bytes, bytearray))
            or metadata.get("kind") != _SHARED_INPUT_KINDS[field]
            or metadata.get("bytes") != len(payload)
            or metadata.get("sha256") != _sha256_hex(bytes(payload))
        ):
            _fail(
                "invalid_artifact_reference",
                f"{field} must resolve to exact catalog bytes",
            )
    return {
        "budget_tokens": 512,
        "comparable_variants": comparable,
        "raw_history_variant": "raw_full_history",
        "shared_input_artifact_ids": shared,
        "hidden_test_visibility": comparison["hidden_test_visibility"],
        "writable_paths": list(_WRITABLE_PATHS),
    }


def designate_v4_claim_runs(
    manifest: Mapping[str, Any],
    *,
    scenario_id: str,
    variant_id: str,
    attempts: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    if scenario_id not in manifest.get("scenario_slots", []):
        _fail("invalid_designation", "scenario is not predeclared")
    if variant_id not in manifest.get("variants", []):
        _fail("invalid_designation", "variant is not predeclared")
    if any(not isinstance(attempt, Mapping) for attempt in attempts):
        _fail("invalid_designation", "every retained attempt must be an object")
    technical_codes = manifest.get("technical_failure_codes")
    if (
        not isinstance(technical_codes, list)
        or not technical_codes
        or any(not isinstance(value, str) or not value for value in technical_codes)
    ):
        _fail("invalid_designation", "technical failure taxonomy must be frozen")
    expected_attempt_hash = _canonical_hash(manifest)
    registration_orders = [attempt.get("registration_order") for attempt in attempts]
    attempt_numbers = [attempt.get("attempt_no") for attempt in attempts]
    if (
        any(not isinstance(value, int) or isinstance(value, bool) for value in registration_orders)
        or registration_orders != sorted(registration_orders)
        or len(registration_orders) != len(set(registration_orders))
        or any(not isinstance(value, int) or isinstance(value, bool) or value < 1 for value in attempt_numbers)
        or attempt_numbers != sorted(attempt_numbers)
        or len(attempt_numbers) != len(set(attempt_numbers))
    ):
        _fail(
            "invalid_designation",
            "attempts must retain unique increasing registration and attempt order",
        )
    retained_ids: list[str] = []
    technical_ids: list[str] = []
    claim_runs: list[Mapping[str, Any]] = []
    diagnostics: list[str] = []
    extras: list[str] = []
    replacements: list[dict[str, str]] = []
    pending_technical: str | None = None

    for attempt in attempts:
        run_id = attempt.get("run_id")
        if not isinstance(run_id, str) or run_id in retained_ids:
            _fail("invalid_designation", "retained attempt IDs must be unique")
        retained_ids.append(run_id)
        if attempt.get("execution_manifest_sha256") != expected_attempt_hash:
            _fail("invalid_designation", "attempt must bind the execution manifest")
        if attempt.get("scenario_id") != scenario_id or attempt.get("variant_id") != variant_id:
            _fail("invalid_designation", "attempt must bind the requested cell")

        designation = attempt.get("designation")
        if designation == "invalidated_abort":
            _fail("invalid_replacement", "manual abort invalidates the claim-bearing cell")
        if designation == "invalidated_technical":
            if pending_technical is not None:
                _fail("invalid_replacement", "technical failures require ordered replacements")
            failure = attempt.get("failure")
            if (
                not isinstance(failure, Mapping)
                or failure.get("code") not in technical_codes
                or attempt.get("outcome")
                != {
                    "status": "invalidated",
                    "stage": "sandbox",
                    "code": "technical_failure",
                }
            ):
                _fail(
                    "invalid_replacement",
                    "technical replacement must match the frozen failure taxonomy",
                )
            pending_technical = run_id
            technical_ids.append(run_id)
            continue
        if designation == "diagnostic":
            diagnostics.append(run_id)
            continue
        if designation != "headline":
            _fail("invalid_designation", "unsupported claim-run designation")
        _validate_completed_outcome(attempt, code="invalid_designation")

        if len(claim_runs) < 3:
            if pending_technical is not None:
                replacements.append(
                    {
                        "invalidated_run_id": pending_technical,
                        "replacement_run_id": run_id,
                    }
                )
                pending_technical = None
            claim_runs.append(attempt)
        else:
            extras.append(run_id)

    if pending_technical is not None or len(claim_runs) != 3:
        _fail("invalid_replacement", "exactly three nontechnical headline runs are required")
    adverse = [run["run_id"] for run in claim_runs if not _suite_passed(run)]
    return {
        "authoritative_evidence": False,
        "authority_note": "designation preview; final evidence requires retained-attempt authority",
        "claim_run_ids": [run["run_id"] for run in claim_runs],
        "retained_run_ids": retained_ids,
        "adverse_run_ids": adverse,
        "technical_attempt_ids": technical_ids,
        "technical_replacements": replacements,
        "ignored_diagnostic_run_ids": diagnostics,
        "ignored_extra_run_ids": extras,
    }


def recompute_v4_aggregate_metrics(
    manifest: Mapping[str, Any],
    *,
    scenario_id: str,
    runs: Sequence[Mapping[str, Any]],
    reported_run_ids: Sequence[str],
    reported_adverse_run_ids: Sequence[str],
    reported_summary: Mapping[str, Any],
) -> dict[str, Any]:
    if scenario_id not in manifest.get("scenario_slots", []):
        _fail("invalid_aggregate", "aggregate scenario must be predeclared")
    if any(not isinstance(run, Mapping) for run in runs):
        _fail("invalid_aggregate", "every aggregate run must be an object")
    expected_run_hash = _canonical_hash(manifest)
    run_ids = [run.get("run_id") for run in runs]
    if (
        any(not isinstance(run_id, str) or not run_id for run_id in run_ids)
        or len(run_ids) != len(set(run_ids))
        or any(
            not isinstance(run_id, str) or not run_id
            for run_id in reported_run_ids
        )
        or list(reported_run_ids) != run_ids
        or len(reported_run_ids) != len(set(reported_run_ids))
    ):
        _fail("invalid_aggregate", "reported run IDs must equal unique input runs")

    adverse = []
    cells: dict[str, list[Mapping[str, Any]]] = {variant: [] for variant in V4_VARIANTS}
    for run in runs:
        if run.get("execution_manifest_sha256") != expected_run_hash:
            _fail("invalid_aggregate", "all runs must bind the execution manifest")
        if run.get("scenario_id") != scenario_id:
            _fail("invalid_aggregate", "all runs must bind the aggregate scenario")
        variant = run.get("variant_id")
        if (
            not isinstance(variant, str)
            or variant not in cells
            or run.get("designation") != "headline"
        ):
            _fail("invalid_aggregate", "aggregate runs must be known headline variants")
        _validate_completed_outcome(run, code="invalid_aggregate")
        cells[variant].append(run)
        if not _suite_passed(run):
            adverse.append(run["run_id"])
    if list(reported_adverse_run_ids) != adverse:
        _fail("invalid_aggregate", "reported adverse runs must equal recomputed adverse runs")
    if any(len(cells[variant]) != 3 for variant in V4_VARIANTS):
        _fail("invalid_aggregate", "SC-005 requires three runs for every variant")

    counts = {variant: _pass_count(cells[variant]) for variant in V4_VARIANTS}
    strongest = max(_COMPARATORS, key=lambda variant: counts[variant])
    baseline_count = counts[strongest]
    recallpack_count = counts["recallpack"]
    if recallpack_count > baseline_count:
        classification = "strict_win"
        numerator = 1
    elif recallpack_count < baseline_count:
        classification = "regression"
        numerator = 0
    else:
        classification = "tie_neutral"
        numerator = 0
    expected_summary = {"numerator": numerator, "denominator": 1, "rate": float(numerator)}
    if not isinstance(reported_summary, Mapping) or dict(reported_summary) != expected_summary:
        _fail("invalid_aggregate", "reported summary must equal SC-005 recomputation")
    return {
        "authoritative_evidence": False,
        "authority_note": "metric preview; final aggregate requires retained-attempt authority",
        "raw_history_excluded": True,
        "strongest_baseline_variant_id": strongest,
        "strongest_baseline_pass_count": baseline_count,
        "recallpack_pass_count": recallpack_count,
        "classification": classification,
        **expected_summary,
    }


def run_v4_floor_diagnostic(
    *,
    manifest: Mapping[str, Any],
    isolated_runner: Mapping[str, Mapping[str, Any]],
    artifact_bytes: Mapping[str, bytes],
) -> dict[str, Any]:
    validate_v4_comparison_contract(manifest, artifact_bytes=artifact_bytes)
    if manifest.get("descope_rung") != "Floor":
        _fail("invalid_rung_grid", "diagnostic runner requires the Floor rung")
    execution_order = manifest.get("execution_order")
    if (
        not isinstance(execution_order, list)
        or len(execution_order) != len(V4_VARIANTS)
        or any(not isinstance(slot, Mapping) for slot in execution_order)
    ):
        _fail(
            "invalid_rung_grid",
            "Floor preview requires one ordered diagnostic slot per variant",
        )
    if (
        [slot.get("variant_id") for slot in execution_order] != list(V4_VARIANTS)
        or [slot.get("slot_index") for slot in execution_order]
        != list(range(len(V4_VARIANTS)))
        or any(slot.get("planned_designation") != "diagnostic" for slot in execution_order)
        or any(
            not isinstance(slot.get("scenario_slot"), str)
            or slot.get("scenario_slot") not in manifest.get("scenario_slots", [])
            for slot in execution_order
        )
    ):
        _fail(
            "invalid_rung_grid",
            "Floor preview requires one ordered diagnostic slot per variant",
        )
    if set(isolated_runner) != set(V4_VARIANTS):
        _fail("invalid_rung_grid", "Floor runner outputs must equal the variant grid")
    manifest_hash = _canonical_hash(manifest)
    runs = []
    run_ids: set[str] = set()
    for slot in execution_order:
        variant = slot["variant_id"]
        output = isolated_runner.get(variant)
        if not isinstance(output, Mapping):
            _fail("invalid_aggregate", "isolated runner output is missing")
        run_id = output.get("run_id")
        full_suite_passed = output.get("full_suite_passed")
        exact_token_count = output.get("exact_token_count")
        context_sha256 = output.get("context_sha256")
        context_bytes = output.get("context_bytes")
        if (
            not isinstance(run_id, str)
            or not run_id
            or run_id in run_ids
            or output.get("variant_id") != variant
        ):
            _fail("invalid_designation", "Floor run identity must be unique and cell-bound")
        if not isinstance(full_suite_passed, bool):
            _fail("invalid_run_outcome", "Floor suite result must be boolean")
        if (
            not isinstance(exact_token_count, int)
            or isinstance(exact_token_count, bool)
            or exact_token_count < 0
            or (variant != "raw_full_history" and exact_token_count > 512)
        ):
            _fail(
                "unequal_comparison_contract",
                "budget-comparable Floor context must fit the exact 512-token budget",
            )
        if (
            not isinstance(context_sha256, str)
            or _SHA256_PATTERN.fullmatch(context_sha256) is None
            or not isinstance(context_bytes, int)
            or isinstance(context_bytes, bool)
            or context_bytes < 0
        ):
            _fail("invalid_artifact_reference", "Floor context evidence is malformed")
        run_ids.add(run_id)
        runs.append(
            {
                "run_id": run_id,
                "execution_manifest_sha256": manifest_hash,
                "scenario_id": slot["scenario_slot"],
                "variant_id": variant,
                "designation": "diagnostic",
                "provider_mode_live": False,
                "outcome": {
                    "status": "completed"
                    if full_suite_passed
                    else "adverse"
                },
                "context_evidence": {
                    "sha256": context_sha256,
                    "exact_token_count": exact_token_count,
                },
                "context_artifact_bytes": context_bytes,
                "test_result": {
                    "full_suite_passed": full_suite_passed
                },
            }
        )

    passed = sum(run["test_result"]["full_suite_passed"] for run in runs)
    summary = {
        "n": len(runs),
        "numerator": passed,
        "denominator": len(runs),
        "rate": passed / len(runs),
    }
    declarations = manifest.get("claim_declarations")
    if (
        not isinstance(declarations, list)
        or not declarations
        or any(not isinstance(declaration, Mapping) for declaration in declarations)
        or any(not _valid_claim_declaration(declaration) for declaration in declarations)
    ):
        _fail("invalid_claim_reference", "Floor claim declarations must be objects")
    return {
        "record_type": "floor_diagnostic_preview",
        "evidence_artifacts_emitted": False,
        "execution_manifest_sha256": manifest_hash,
        "runs": runs,
        "retained_run_ids": [run["run_id"] for run in runs],
        "summary": summary,
        "claims": [
            _disabled_claim(item, "evidence_incomplete", []) for item in declarations
        ],
        "limitations": [
            "This preview is not an EvaluationRun, AggregateReport, or EvidenceManifest.",
            "Schema-valid evidence requires the still-pending isolated evaluator and artifact pipeline.",
        ],
    }


def _disabled_claim(
    declaration: Mapping[str, Any],
    reason: str,
    evidence_ids: list[str],
) -> dict[str, Any]:
    return {
        "claim_id": declaration["claim_id"],
        "claim_type": declaration["claim_type"],
        "activation_rule_id": declaration["activation_rule_id"],
        "status": "disabled",
        "decision_reason": reason,
        "statement": declaration["statement"],
        "evidence_artifact_ids": evidence_ids,
        "rerunnable_command": declaration["rerunnable_command"],
        "limitations": list(declaration["limitations"]),
    }


def _valid_claim_declaration(declaration: Mapping[str, Any]) -> bool:
    required_text = (
        "claim_id",
        "claim_type",
        "activation_rule_id",
        "statement",
        "rerunnable_command",
    )
    limitations = declaration.get("limitations")
    return (
        all(
            isinstance(declaration.get(field), str) and bool(declaration[field])
            for field in required_text
        )
        and isinstance(limitations, list)
        and all(isinstance(item, str) and bool(item) for item in limitations)
    )


def _pass_count(runs: Sequence[Mapping[str, Any]]) -> int:
    return sum(_suite_passed(run) for run in runs)


def _suite_passed(run: Mapping[str, Any]) -> bool:
    result = run.get("test_result")
    return isinstance(result, Mapping) and result.get("full_suite_passed") is True


def _validate_completed_outcome(run: Mapping[str, Any], *, code: str) -> None:
    result = run.get("test_result")
    if not isinstance(result, Mapping) or not isinstance(
        result.get("full_suite_passed"), bool
    ):
        _fail(code, "headline run must carry a boolean suite result")
    expected = (
        {"status": "completed", "stage": "complete", "code": "success"}
        if result["full_suite_passed"]
        else {
            "status": "adverse",
            "stage": "hidden_test",
            "code": "hidden_tests_failed",
        }
    )
    if run.get("outcome") != expected:
        _fail(code, "headline run outcome must match the frozen truth table")


def _canonical_hash(value: Mapping[str, Any]) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def _fail(code: str, detail: str) -> None:
    raise ValueError(f"4.0 {code} / {detail}")
