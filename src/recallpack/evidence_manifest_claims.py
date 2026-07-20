from __future__ import annotations

from collections import defaultdict
from typing import Any, Mapping, Sequence


def validate_manifest_claims(
    record: Mapping[str, Any],
    execution_manifest: Mapping[str, Any],
    *,
    aggregates_by_claim: Mapping[str, Mapping[str, Any]],
    retained: Sequence[Mapping[str, Any]],
    accepted: Sequence[Mapping[str, Any]],
) -> list[tuple[str, str, str]]:
    declarations = execution_manifest.get("claim_declarations", [])
    claims = record.get("claims", [])
    errors: list[tuple[str, str, str]] = []
    if not isinstance(declarations, list) or not isinstance(claims, list):
        return errors

    declared = [item.get("claim_id") for item in declarations]
    reported = [item.get("claim_id") for item in claims]
    if len(reported) != len(set(reported)) or set(reported) != set(declared):
        errors.append(
            (
                "invalid_claim_reference",
                "/claims",
                "claim IDs must be unique and exactly equal frozen declarations",
            )
        )
        return errors

    declaration_by_id = {item["claim_id"]: item for item in declarations}
    for index, claim in enumerate(claims):
        declaration = declaration_by_id[claim["claim_id"]]
        pointer = f"/claims/{index}"
        errors.extend(_validate_frozen_fields(claim, declaration, pointer))
        if record.get("status") == "partial":
            errors.extend(_validate_partial_claim(claim, pointer))
            continue
        aggregate = aggregates_by_claim.get(claim["claim_id"])
        errors.extend(
            _validate_final_claim(
                claim,
                declaration,
                aggregate,
                execution_manifest,
                retained,
                accepted,
                pointer,
            )
        )
    return errors


def _validate_frozen_fields(
    claim: Mapping[str, Any],
    declaration: Mapping[str, Any],
    pointer: str,
) -> list[tuple[str, str, str]]:
    errors = []
    for field in (
        "claim_type",
        "activation_rule_id",
        "statement",
        "rerunnable_command",
        "limitations",
    ):
        if claim.get(field) != declaration.get(field):
            errors.append(
                (
                    "invalid_claim_reference",
                    f"{pointer}/{field}",
                    f"claim {field} must equal the frozen declaration",
                )
            )
    return errors


def _validate_partial_claim(
    claim: Mapping[str, Any],
    pointer: str,
) -> list[tuple[str, str, str]]:
    expected = ("disabled", "evidence_incomplete", [])
    actual = (
        claim.get("status"),
        claim.get("decision_reason"),
        claim.get("evidence_artifact_ids"),
    )
    if actual == expected:
        return []
    return [
        (
            "invalid_claim_reference",
            pointer,
            "partial claims must be disabled evidence-incomplete with no evidence IDs",
        )
    ]


def _validate_final_claim(
    claim: Mapping[str, Any],
    declaration: Mapping[str, Any],
    aggregate: Mapping[str, Any] | None,
    manifest: Mapping[str, Any],
    retained: Sequence[Mapping[str, Any]],
    accepted: Sequence[Mapping[str, Any]],
    pointer: str,
) -> list[tuple[str, str, str]]:
    if aggregate is None:
        return [
            (
                "incomplete_final_evidence",
                pointer,
                "final claim must resolve to exactly one validated aggregate",
            )
        ]

    errors: list[tuple[str, str, str]] = []
    aggregate_id = aggregate.get("aggregate_id")
    if claim.get("evidence_artifact_ids") != [aggregate_id]:
        errors.append(
            (
                "invalid_claim_reference",
                f"{pointer}/evidence_artifact_ids",
                "final claim evidence must name its single validated aggregate",
            )
        )

    if (
        declaration.get("activation_rule_id") == "sc005_downstream_superiority"
        and not _downstream_aggregate_covers(aggregate, manifest, accepted)
    ):
        errors.append(
            (
                "incomplete_final_evidence",
                f"{pointer}/evidence_artifact_ids",
                "downstream claim aggregate must cover every SC-005 comparator and RecallPack run",
            )
        )

    rung = manifest.get("descope_rung")
    eligible = declaration.get("eligible_rungs", [])
    if rung not in eligible:
        expected = ("disabled", "rung_ineligible")
    else:
        passed = _activation_passes(
            declaration.get("activation_rule_id"),
            aggregate,
            manifest,
            retained,
            accepted,
        )
        expected = (
            ("enabled", "threshold_passed")
            if passed
            else ("disabled", "threshold_failed")
        )
    actual = (claim.get("status"), claim.get("decision_reason"))
    if actual != expected:
        errors.append(
            (
                "invalid_claim_reference",
                pointer,
                "final claim status must equal recomputed activation outcome",
            )
        )
    return errors


def _activation_passes(
    rule_id: Any,
    aggregate: Mapping[str, Any],
    manifest: Mapping[str, Any],
    retained: Sequence[Mapping[str, Any]],
    accepted: Sequence[Mapping[str, Any]],
) -> bool:
    if rule_id == "structural_runtime_gate":
        return _structural_passes(aggregate, accepted)
    if rule_id == "sc005_downstream_superiority":
        return _downstream_passes(aggregate, manifest, accepted)
    if rule_id == "sc002_false_supersession":
        return _false_supersession_passes(aggregate, retained)
    return False


def _metric(aggregate: Mapping[str, Any], metric_id: str) -> Mapping[str, Any] | None:
    metrics = aggregate.get("metrics")
    if not isinstance(metrics, list) or len(metrics) != 1:
        return None
    metric = metrics[0]
    if not isinstance(metric, Mapping) or metric.get("metric_id") != metric_id:
        return None
    return metric


def _structural_passes(
    aggregate: Mapping[str, Any],
    accepted: Sequence[Mapping[str, Any]],
) -> bool:
    metric = _metric(aggregate, "runtime_contract_success")
    expected_run_ids = [item["run"]["run_id"] for item in accepted]
    return bool(
        metric
        and expected_run_ids
        and aggregate.get("run_ids") == expected_run_ids
        and metric.get("n") == len(expected_run_ids)
        and metric.get("numerator") == metric.get("denominator") == metric.get("n")
        and metric.get("rate") == 1
    )


def _downstream_passes(
    aggregate: Mapping[str, Any],
    manifest: Mapping[str, Any],
    accepted: Sequence[Mapping[str, Any]],
) -> bool:
    if _metric(aggregate, "downstream_full_suite_success") is None:
        return False
    scenarios = list(manifest.get("scenario_slots", []))
    comparability = manifest.get("comparison_contract", {}).get(
        "variant_comparability", {}
    )
    comparators = [
        variant
        for variant, policy in comparability.items()
        if isinstance(policy, Mapping)
        and policy.get("headline_comparator_eligible") is True
    ]
    if len(scenarios) != 4 or not comparators:
        return False

    cells: dict[tuple[str, str], list[Mapping[str, Any]]] = defaultdict(list)
    for item in accepted:
        run = item["run"]
        if run.get("designation") == "headline":
            cells[(run.get("scenario_id"), run.get("variant_id"))].append(run)

    wins = regressions = 0
    for scenario in scenarios:
        recallpack_runs = cells[(scenario, "recallpack")]
        baseline_runs = [cells[(scenario, variant)] for variant in comparators]
        if len(recallpack_runs) != 3 or any(len(runs) != 3 for runs in baseline_runs):
            return False
        recallpack_score = _pass_count(recallpack_runs)
        baseline_score = max(_pass_count(runs) for runs in baseline_runs)
        wins += recallpack_score > baseline_score
        regressions += recallpack_score < baseline_score
    return bool(
        _downstream_aggregate_covers(aggregate, manifest, accepted)
        and wins >= 2
        and regressions == 0
    )


def _downstream_aggregate_covers(
    aggregate: Mapping[str, Any],
    manifest: Mapping[str, Any],
    accepted: Sequence[Mapping[str, Any]],
) -> bool:
    comparability = manifest.get("comparison_contract", {}).get(
        "variant_comparability", {}
    )
    eligible = {
        variant
        for variant, policy in comparability.items()
        if isinstance(policy, Mapping)
        and policy.get("headline_comparator_eligible") is True
    }
    eligible.add("recallpack")
    scenarios = set(manifest.get("scenario_slots", []))
    required = {
        item["run"]["run_id"]
        for item in accepted
        if item["run"].get("designation") == "headline"
        and item["run"].get("scenario_id") in scenarios
        and item["run"].get("variant_id") in eligible
    }
    return bool(required and required <= set(aggregate.get("run_ids", [])))


def _pass_count(runs: Sequence[Mapping[str, Any]]) -> int:
    return sum(
        isinstance(run.get("test_result"), Mapping)
        and run["test_result"].get("full_suite_passed") is True
        for run in runs
    )


def _false_supersession_passes(
    aggregate: Mapping[str, Any],
    retained: Sequence[Mapping[str, Any]],
) -> bool:
    metric = _metric(aggregate, "false_supersession_rate")
    if not metric:
        return False
    scope = aggregate.get("scope", {})
    opportunities: dict[str, str] = {}
    for item in retained:
        run = item["run"]
        if (
            run.get("scenario_id") not in scope.get("scenario_ids", [])
            or run.get("variant_id") != "recallpack"
            or run.get("designation") != "headline"
        ):
            continue
        for opportunity in run.get("relation_opportunities", []):
            opportunities[opportunity["opportunity_id"]] = opportunity["relation_kind"]
    kinds = list(opportunities.values())
    return bool(
        metric.get("n", 0) >= 40
        and metric.get("numerator") == 0
        and metric.get("denominator") == metric.get("n")
        and metric.get("rate") == 0
        and kinds.count("true_supersession") >= 15
        and kinds.count("hard_negative") >= 15
    )
