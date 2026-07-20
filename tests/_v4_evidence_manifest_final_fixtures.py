from __future__ import annotations

import copy

from tests._v4_evidence_aggregate_fixtures import (
    build_simulated_full_accepted_run_universe,
    build_test_only_retained_attempt_authority,
    build_test_only_retained_attempt_loader,
)
from tests._v4_evidence_common import canonical_sha256
from tests._v4_evidence_run_fixtures import (
    build_aggregate_report,
    build_aggregate_scope,
    build_artifact_bytes,
    build_evidence_manifest,
)


def build_test_only_simulated_complete_evidence_packet(
    *,
    downstream_wins: bool = False,
) -> dict[str, object]:
    universe = build_simulated_full_accepted_run_universe()
    manifest = universe["manifest"]
    all_runs = universe["all_runs"]
    if downstream_wins:
        _apply_two_scenario_downstream_wins(all_runs)
        universe["retained_runs"] = copy.deepcopy(all_runs)
        universe["retained_attempt_authority"] = (
            build_test_only_retained_attempt_authority(manifest, all_runs)
        )
        universe["retained_attempt_loader"] = build_test_only_retained_attempt_loader(
            manifest,
            all_runs,
        )
    scenario_ids = list(manifest["scenario_slots"])
    variant_ids = list(manifest["variants"])
    adverse_run_ids = [
        run["run_id"]
        for run in all_runs
        if run["outcome"]["status"] == "adverse"
    ]
    downstream_passes = sum(
        run["test_result"]["full_suite_passed"] for run in all_runs
    )

    structural = build_aggregate_report(
        manifest,
        aggregate_id="agg_StructuralAll",
        claim_id="claim_structural_runtime",
        claim_type="structural_runtime",
        run_records=all_runs,
        run_ids=[run["run_id"] for run in all_runs],
        adverse_run_ids=adverse_run_ids,
        scope=build_aggregate_scope(
            all_runs,
            designation="headline",
            scenario_ids=scenario_ids,
            variant_ids=variant_ids,
        ),
        metrics=[
            {
                "metric_id": "runtime_contract_success",
                "n": 60,
                "numerator": 60,
                "denominator": 60,
                "rate": 1.0,
            }
        ],
    )
    downstream = build_aggregate_report(
        manifest,
        aggregate_id="agg_DownstreamAll",
        claim_id="claim_downstream_superiority",
        claim_type="downstream_superiority",
        run_records=all_runs,
        run_ids=[run["run_id"] for run in all_runs],
        adverse_run_ids=adverse_run_ids,
        scope=build_aggregate_scope(
            all_runs,
            designation="headline",
            scenario_ids=scenario_ids,
            variant_ids=variant_ids,
        ),
        metrics=[
            {
                "metric_id": "downstream_full_suite_success",
                "n": 60,
                "numerator": downstream_passes,
                "denominator": 60,
                "rate": downstream_passes / 60,
            }
        ],
    )
    recallpack_runs = [run for run in all_runs if run["variant_id"] == "recallpack"]
    false_supersession = build_aggregate_report(
        manifest,
        aggregate_id="agg_FalseSupersessionAll",
        claim_id="claim_false_supersession",
        claim_type="false_supersession_rate",
        run_records=recallpack_runs,
        run_ids=[run["run_id"] for run in recallpack_runs],
        adverse_run_ids=[],
        scope=build_aggregate_scope(
            recallpack_runs,
            designation="headline",
            scenario_ids=scenario_ids,
            variant_ids=["recallpack"],
        ),
        metrics=[
            {
                "metric_id": "false_supersession_rate",
                "n": 8,
                "numerator": 0,
                "denominator": 8,
                "rate": 0.0,
            }
        ],
    )
    aggregates = [structural, downstream, false_supersession]
    final_evidence = build_evidence_manifest(
        manifest,
        run_records=all_runs,
        aggregate_records=aggregates,
        status="final",
    )
    final_evidence["evidence_manifest_id"] = "evidence_Final1"
    final_evidence["claims"] = _final_claims(
        manifest,
        aggregates,
        downstream_enabled=downstream_wins,
    )

    partial_runs = [
        run
        for run in all_runs
        if run["scenario_id"] == "projectodyssey"
        and run["variant_id"] == "semantic_rerank"
    ]
    subset_structural_aggregate = build_aggregate_report(
        manifest,
        aggregate_id="agg_SubsetStructural",
        claim_id="claim_structural_runtime",
        claim_type="structural_runtime",
        run_records=partial_runs,
        run_ids=[run["run_id"] for run in partial_runs],
        adverse_run_ids=[
            run["run_id"]
            for run in partial_runs
            if run["outcome"]["status"] == "adverse"
        ],
        scope=build_aggregate_scope(
            partial_runs,
            designation="headline",
            scenario_ids=["projectodyssey"],
            variant_ids=["semantic_rerank"],
        ),
        metrics=[
            {
                "metric_id": "runtime_contract_success",
                "n": 3,
                "numerator": 3,
                "denominator": 3,
                "rate": 1.0,
            }
        ],
    )
    subset_downstream_aggregate = build_aggregate_report(
        manifest,
        aggregate_id="agg_SubsetDownstream",
        claim_id="claim_downstream_superiority",
        claim_type="downstream_superiority",
        run_records=partial_runs,
        run_ids=[run["run_id"] for run in partial_runs],
        adverse_run_ids=[
            run["run_id"]
            for run in partial_runs
            if run["outcome"]["status"] == "adverse"
        ],
        scope=build_aggregate_scope(
            partial_runs,
            designation="headline",
            scenario_ids=["projectodyssey"],
            variant_ids=["semantic_rerank"],
        ),
        metrics=[
            {
                "metric_id": "downstream_full_suite_success",
                "n": 3,
                "numerator": sum(
                    run["test_result"]["full_suite_passed"]
                    for run in partial_runs
                ),
                "denominator": 3,
                "rate": sum(
                    run["test_result"]["full_suite_passed"]
                    for run in partial_runs
                )
                / 3,
            }
        ],
    )
    partial_evidence = build_evidence_manifest(
        manifest,
        run_records=partial_runs,
        aggregate_records=[],
        status="partial",
    )
    partial_evidence["evidence_manifest_id"] = "evidence_Partial1"
    partial_evidence["claims"] = _partial_claims(manifest)
    final_evidence["previous_evidence_manifest_sha256"] = canonical_sha256(
        partial_evidence
    )

    artifact_bytes = build_artifact_bytes(
        manifest,
        source_ledgers=universe["all_source_ledgers"],
        simulated_external_holdout=universe["simulated_external_holdout"],
        run_records=all_runs,
        aggregate_records=aggregates
        + [subset_structural_aggregate, subset_downstream_aggregate],
        evidence_manifest=final_evidence,
    )
    universe.update(
        {
            "aggregates": aggregates,
            "structural_aggregate": structural,
            "downstream_aggregate": downstream,
            "false_supersession_aggregate": false_supersession,
            "evidence": final_evidence,
            "partial_evidence": partial_evidence,
            "partial_runs": partial_runs,
            "subset_structural_aggregate": subset_structural_aggregate,
            "subset_downstream_aggregate": subset_downstream_aggregate,
            "artifact_bytes": artifact_bytes,
        }
    )
    return universe


def _final_claims(
    manifest: dict[str, object],
    aggregates: list[dict[str, object]],
    *,
    downstream_enabled: bool,
) -> list[dict[str, object]]:
    aggregate_by_claim = {aggregate["claim_id"]: aggregate for aggregate in aggregates}
    claims = []
    for declaration in manifest["claim_declarations"]:
        enabled = declaration["claim_type"] == "structural_runtime" or (
            declaration["claim_type"] == "downstream_superiority"
            and downstream_enabled
        )
        claims.append(
            {
                "claim_id": declaration["claim_id"],
                "claim_type": declaration["claim_type"],
                "activation_rule_id": declaration["activation_rule_id"],
                "status": "enabled" if enabled else "disabled",
                "decision_reason": "threshold_passed"
                if enabled
                else "threshold_failed",
                "statement": declaration["statement"],
                "evidence_artifact_ids": [
                    aggregate_by_claim[declaration["claim_id"]]["aggregate_id"]
                ],
                "rerunnable_command": declaration["rerunnable_command"],
                "limitations": copy.deepcopy(declaration["limitations"]),
            }
        )
    return claims


def _partial_claims(manifest: dict[str, object]) -> list[dict[str, object]]:
    return [
        {
            "claim_id": declaration["claim_id"],
            "claim_type": declaration["claim_type"],
            "activation_rule_id": declaration["activation_rule_id"],
            "status": "disabled",
            "decision_reason": "evidence_incomplete",
            "statement": declaration["statement"],
            "evidence_artifact_ids": [],
            "rerunnable_command": declaration["rerunnable_command"],
            "limitations": copy.deepcopy(declaration["limitations"]),
        }
        for declaration in manifest["claim_declarations"]
    ]


def _apply_two_scenario_downstream_wins(
    runs: list[dict[str, object]],
) -> None:
    comparator_variants = {
        "semantic_rerank",
        "recency_aware",
        "recall_time_resolver",
    }
    for run in runs:
        if (
            run["scenario_id"] not in {"projectodyssey", "deepagents"}
            or run["variant_id"] not in comparator_variants
        ):
            continue
        run["outcome"] = {
            "status": "adverse",
            "stage": "hidden_test",
            "code": "hidden_tests_failed",
        }
        run["test_result"].update(
            {
                "full_suite_passed": False,
                "passed": 0,
                "failed": 1,
                "exit_code": 1,
            }
        )
        run["test_result"]["tests"][0]["status"] = "failed"
