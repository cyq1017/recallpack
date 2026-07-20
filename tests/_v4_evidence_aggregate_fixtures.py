from __future__ import annotations

import copy

from recallpack.evidence_authority import TestOnlyTrustedRetainedAttemptLoader

from tests._v4_evidence_common import canonical_sha256
from tests._v4_evidence_manifest_fixtures import (
    build_full_execution_manifest,
    build_relation_label_ledgers,
    build_simulated_external_holdout_bundle,
    build_source_ledgers,
)
from tests._v4_evidence_run_fixtures import (
    build_aggregate_report,
    build_aggregate_scope,
    build_artifact_bytes,
    build_evaluation_run,
    build_evidence_manifest,
    build_relation_opportunity,
)


def _merged_source_ledgers(
    source_ledgers: dict[str, dict[str, object]],
    simulated_external_holdout: dict[str, object],
) -> dict[str, dict[str, object]]:
    merged = copy.deepcopy(source_ledgers)
    merged[simulated_external_holdout["scenario_slot"]] = copy.deepcopy(
        simulated_external_holdout["source_ledger"]
    )
    return merged


def _merged_relation_label_ledgers(
    relation_label_ledgers: dict[str, dict[str, object]],
    simulated_external_holdout: dict[str, object],
) -> dict[str, dict[str, object]]:
    merged = copy.deepcopy(relation_label_ledgers)
    merged[simulated_external_holdout["scenario_slot"]] = copy.deepcopy(
        simulated_external_holdout["relation_label_ledger"]
    )
    return merged


def _relation_opportunities_for_ledger(
    scenario_id: str,
    ledger: dict[str, object],
) -> list[dict[str, object]]:
    opportunities: list[dict[str, object]] = []
    for entry in ledger.get("entries", []):
        if not isinstance(entry, dict):
            continue
        relation_kind = entry["relation_kind"]
        opportunities.append(
            build_relation_opportunity(
                opportunity_id=entry["opportunity_id"],
                scenario_id=scenario_id,
                relation_kind=relation_kind,
                decision=(
                    "keep_independent"
                    if relation_kind == "hard_negative"
                    else "inactivate_prior"
                ),
                outcome="correct",
                prior_source_ref=entry["prior_source_ref"],
                candidate_source_ref=entry["candidate_source_ref"],
            )
        )
    return opportunities


def _compact_token(value: str) -> str:
    return "".join(char for char in value if char.isalnum())


def build_test_only_retained_attempt_authority(
    manifest: dict[str, object],
    retained_runs: list[dict[str, object]],
    *,
    finalization_states: dict[str, str] | None = None,
) -> dict[str, object]:
    states = finalization_states or {}
    entries = []
    for registration_order, run in enumerate(retained_runs):
        designation = run["designation"]
        default_state = "accepted"
        if designation == "invalidated_technical":
            default_state = "invalidated_technical"
        elif designation == "invalidated_abort":
            default_state = "invalidated_abort"
        entries.append(
            {
                "run_artifact_id": f"run_{run['run_id']}",
                "run_id": run["run_id"],
                "canonical_run_sha256": canonical_sha256(run),
                "slot_index": run["slot_index"],
                "attempt_no": run["attempt_no"],
                "designation": designation,
                "registration_order": registration_order,
                "execution_manifest_sha256": run["execution_manifest_sha256"],
                "finalization_state": states.get(run["run_id"], default_state),
            }
        )
    return {
        "authority_kind": "test_only_sealed_retained_attempt_authority",
        "simulation_marker": "test_only_sealed_retained_attempt_authority",
        "execution_manifest_sha256": canonical_sha256(manifest),
        "authority_state": "finalized",
        "entry_count": len(entries),
        "population_sha256": canonical_sha256(entries),
        "entries": entries,
    }


def build_test_only_retained_attempt_loader(
    manifest: dict[str, object],
    retained_runs: list[dict[str, object]],
    *,
    finalization_states: dict[str, str] | None = None,
) -> TestOnlyTrustedRetainedAttemptLoader:
    return TestOnlyTrustedRetainedAttemptLoader(
        build_test_only_retained_attempt_authority(
            manifest,
            retained_runs,
            finalization_states=finalization_states,
        )
    )


def _align_selected_sources(universe: dict[str, object]) -> None:
    for run in universe["all_runs"]:
        entries = universe["all_source_ledgers"][run["scenario_id"]]["entries"]
        run["selected_sources"] = [entries[0]["source_ref"]]


def build_simulated_full_accepted_run_universe(
    *,
    source_ledgers: dict[str, dict[str, object]] | None = None,
    relation_label_ledgers: dict[str, dict[str, object]] | None = None,
    simulated_external_holdout: dict[str, object] | None = None,
) -> dict[str, object]:
    public_source_ledgers = copy.deepcopy(source_ledgers or build_source_ledgers())
    public_relation_ledgers = copy.deepcopy(
        relation_label_ledgers or build_relation_label_ledgers(public_source_ledgers)
    )
    holdout_bundle = copy.deepcopy(
        simulated_external_holdout or build_simulated_external_holdout_bundle()
    )
    manifest = build_full_execution_manifest(
        source_ledgers=public_source_ledgers,
        relation_label_ledgers=public_relation_ledgers,
        simulated_external_holdout=holdout_bundle,
    )
    all_source_ledgers = _merged_source_ledgers(public_source_ledgers, holdout_bundle)
    all_relation_ledgers = _merged_relation_label_ledgers(public_relation_ledgers, holdout_bundle)
    all_runs: list[dict[str, object]] = []
    for slot in manifest["execution_order"]:
        scenario_id = slot["scenario_slot"]
        variant_id = slot["variant_id"]
        repetition = slot["repetition"]
        relation_opportunities = []
        if variant_id == "recallpack":
            relation_opportunities = _relation_opportunities_for_ledger(
                scenario_id,
                all_relation_ledgers[scenario_id],
            )
        all_runs.append(
            build_evaluation_run(
                manifest,
                run_id=(
                    f"eval_{_compact_token(scenario_id)}"
                    f"{_compact_token(variant_id)}R{repetition}{slot['slot_index']}"
                ),
                scenario_id=scenario_id,
                variant_id=variant_id,
                slot_index=slot["slot_index"],
                attempt_no=repetition,
                designation=slot["planned_designation"],
                relation_opportunities=relation_opportunities,
            )
        )
    artifact_bytes = build_artifact_bytes(
        manifest,
        source_ledgers=all_source_ledgers,
        simulated_external_holdout=holdout_bundle,
        run_records=all_runs,
    )
    return {
        "manifest": manifest,
        "public_source_ledgers": public_source_ledgers,
        "public_relation_label_ledgers": public_relation_ledgers,
        "simulated_external_holdout": holdout_bundle,
        "all_source_ledgers": all_source_ledgers,
        "all_relation_label_ledgers": all_relation_ledgers,
        "all_runs": all_runs,
        "retained_runs": copy.deepcopy(all_runs),
        "retained_attempt_authority": build_test_only_retained_attempt_authority(manifest, all_runs),
        "retained_attempt_loader": build_test_only_retained_attempt_loader(manifest, all_runs),
        "artifact_bytes": artifact_bytes,
        "test_only_simulation_marker": holdout_bundle["custody_kind"],
    }


def scope_run_records(
    universe: dict[str, object],
    *,
    scenario_ids: list[str],
    variant_ids: list[str],
    designation: str = "headline",
) -> list[dict[str, object]]:
    return [
        copy.deepcopy(run)
        for run in universe["all_runs"]
        if run["designation"] == designation
        and run["scenario_id"] in scenario_ids
        and run["variant_id"] in variant_ids
    ]


def build_test_only_simulated_runtime_contract_scope_packet() -> dict[str, object]:
    universe = build_simulated_full_accepted_run_universe()
    contributors = scope_run_records(
        universe,
        scenario_ids=["projectodyssey"],
        variant_ids=["semantic_rerank"],
    )
    aggregate = build_aggregate_report(
        universe["manifest"],
        run_records=contributors,
        run_ids=[run["run_id"] for run in contributors],
        adverse_run_ids=[],
        numerator=3,
        denominator=3,
        n=3,
        rate=1.0,
        scope=build_aggregate_scope(
            contributors,
            designation="headline",
            scenario_ids=["projectodyssey"],
            variant_ids=["semantic_rerank"],
        ),
    )
    universe["contributors"] = contributors
    universe["aggregate"] = aggregate
    return universe


def build_test_only_simulated_runtime_contract_retained_attempt_packet() -> dict[str, object]:
    universe = build_test_only_simulated_runtime_contract_scope_packet()
    canonical_same_slot_run = copy.deepcopy(universe["contributors"][0])
    canonical_same_slot_run["attempt_no"] = 101
    alternate_same_slot_run = build_evaluation_run(
        universe["manifest"],
        run_id="eval_ProjectOdysseySemanticRerankAlt102",
        scenario_id=canonical_same_slot_run["scenario_id"],
        variant_id=canonical_same_slot_run["variant_id"],
        slot_index=canonical_same_slot_run["slot_index"],
        attempt_no=102,
    )
    invalidated_same_slot_run = build_evaluation_run(
        universe["manifest"],
        run_id="eval_ProjectOdysseySemanticRerankInvalid100",
        scenario_id=canonical_same_slot_run["scenario_id"],
        variant_id=canonical_same_slot_run["variant_id"],
        slot_index=canonical_same_slot_run["slot_index"],
        attempt_no=100,
        designation="invalidated_technical",
    )
    accepted_runs = [
        (
            copy.deepcopy(canonical_same_slot_run)
            if run["run_id"] == canonical_same_slot_run["run_id"]
            else copy.deepcopy(run)
        )
        for run in universe["all_runs"]
    ]
    retained_runs = [
        copy.deepcopy(run)
        for run in accepted_runs
        if run["run_id"] != canonical_same_slot_run["run_id"]
    ] + [
        invalidated_same_slot_run,
        canonical_same_slot_run,
        alternate_same_slot_run,
    ]
    universe["all_runs"] = accepted_runs
    universe["retained_runs"] = retained_runs
    universe["contributors"] = scope_run_records(
        universe,
        scenario_ids=["projectodyssey"],
        variant_ids=["semantic_rerank"],
    )
    universe["aggregate"] = build_aggregate_report(
        universe["manifest"],
        run_records=universe["contributors"],
        run_ids=[run["run_id"] for run in universe["contributors"]],
        adverse_run_ids=[],
        numerator=3,
        denominator=3,
        n=3,
        rate=1.0,
        scope=build_aggregate_scope(
            universe["contributors"],
            designation="headline",
            scenario_ids=["projectodyssey"],
            variant_ids=["semantic_rerank"],
        ),
    )
    universe["artifact_bytes"] = build_artifact_bytes(
        universe["manifest"],
        source_ledgers=universe["all_source_ledgers"],
        simulated_external_holdout=universe["simulated_external_holdout"],
        run_records=retained_runs,
    )
    universe["alternate_same_slot_run"] = alternate_same_slot_run
    universe["invalidated_same_slot_run"] = invalidated_same_slot_run
    universe["canonical_same_slot_run"] = canonical_same_slot_run
    universe["retained_attempt_authority"] = build_test_only_retained_attempt_authority(
        universe["manifest"],
        universe["retained_runs"],
        finalization_states={
            alternate_same_slot_run["run_id"]: "retained_non_authoritative",
            invalidated_same_slot_run["run_id"]: "invalidated_technical",
        },
    )
    universe["retained_attempt_loader"] = build_test_only_retained_attempt_loader(
        universe["manifest"],
        universe["retained_runs"],
        finalization_states={
            alternate_same_slot_run["run_id"]: "retained_non_authoritative",
            invalidated_same_slot_run["run_id"]: "invalidated_technical",
        },
    )
    return universe


def build_test_only_simulated_false_supersession_scope_packet() -> dict[str, object]:
    universe = build_simulated_full_accepted_run_universe()
    canonical_runs = [
        run
        for run in universe["all_runs"]
        if run["scenario_id"] == "projectodyssey" and run["variant_id"] == "recallpack"
    ]
    canonical_runs[1]["relation_opportunities"][0]["decision"] = "inactivate_prior"
    canonical_runs[1]["relation_opportunities"][0]["outcome"] = "false_supersession"
    canonical_runs[1]["relation_opportunities"][1]["decision"] = "keep_independent"
    canonical_runs[1]["relation_opportunities"][1]["outcome"] = "missed_true_supersession"
    universe["artifact_bytes"] = build_artifact_bytes(
        universe["manifest"],
        source_ledgers=universe["all_source_ledgers"],
        simulated_external_holdout=universe["simulated_external_holdout"],
        run_records=universe["all_runs"],
    )
    contributors = scope_run_records(
        universe,
        scenario_ids=["projectodyssey"],
        variant_ids=["recallpack"],
    )
    aggregate = build_aggregate_report(
        universe["manifest"],
        claim_id="claim_false_supersession",
        claim_type="false_supersession_rate",
        run_records=contributors,
        run_ids=[run["run_id"] for run in contributors],
        adverse_run_ids=[],
        scope=build_aggregate_scope(
            contributors,
            designation="headline",
            scenario_ids=["projectodyssey"],
            variant_ids=["recallpack"],
        ),
        metrics=[
            {
                "metric_id": "false_supersession_rate",
                "n": 2,
                "numerator": 1,
                "denominator": 2,
                "rate": 0.5,
            }
        ],
    )
    universe["contributors"] = contributors
    universe["aggregate"] = aggregate
    universe["retained_attempt_authority"] = build_test_only_retained_attempt_authority(
        universe["manifest"],
        universe["all_runs"],
    )
    universe["retained_attempt_loader"] = build_test_only_retained_attempt_loader(
        universe["manifest"],
        universe["all_runs"],
    )
    return universe


def build_test_only_simulated_retained_adverse_false_supersession_packet(
) -> dict[str, object]:
    universe = build_simulated_full_accepted_run_universe()
    contributors = scope_run_records(
        universe,
        scenario_ids=["projectodyssey"],
        variant_ids=["recallpack"],
    )
    accepted_same_slot_run = copy.deepcopy(contributors[0])
    retained_adverse_run = copy.deepcopy(accepted_same_slot_run)
    retained_adverse_run["run_id"] = "eval_ProjectOdysseyRecallPackRetainedAdverse99"
    retained_adverse_run["attempt_no"] = 99
    hard_negative = next(
        opportunity
        for opportunity in retained_adverse_run["relation_opportunities"]
        if opportunity["relation_kind"] == "hard_negative"
    )
    hard_negative["decision"] = "inactivate_prior"
    hard_negative["outcome"] = "false_supersession"
    retained_runs = copy.deepcopy(universe["all_runs"]) + [retained_adverse_run]
    universe["retained_runs"] = retained_runs
    universe["retained_adverse_run"] = retained_adverse_run
    universe["accepted_same_slot_run"] = accepted_same_slot_run
    universe["artifact_bytes"] = build_artifact_bytes(
        universe["manifest"],
        source_ledgers=universe["all_source_ledgers"],
        simulated_external_holdout=universe["simulated_external_holdout"],
        run_records=retained_runs,
    )
    universe["aggregate"] = build_aggregate_report(
        universe["manifest"],
        claim_id="claim_false_supersession",
        claim_type="false_supersession_rate",
        run_records=contributors,
        run_ids=[run["run_id"] for run in contributors],
        adverse_run_ids=[],
        scope=build_aggregate_scope(
            contributors,
            designation="headline",
            scenario_ids=["projectodyssey"],
            variant_ids=["recallpack"],
        ),
        metrics=[
            {
                "metric_id": "false_supersession_rate",
                "n": 2,
                "numerator": 0,
                "denominator": 2,
                "rate": 0.0,
            }
        ],
    )
    universe["contributors"] = contributors
    finalization_states = {
        retained_adverse_run["run_id"]: "retained_non_authoritative",
    }
    universe["retained_attempt_authority"] = build_test_only_retained_attempt_authority(
        universe["manifest"],
        retained_runs,
        finalization_states=finalization_states,
    )
    universe["retained_attempt_loader"] = build_test_only_retained_attempt_loader(
        universe["manifest"],
        retained_runs,
        finalization_states=finalization_states,
    )
    return universe


def build_test_only_simulated_zero_denominator_false_supersession_packet(
) -> dict[str, object]:
    public_source_ledgers = build_source_ledgers()
    public_relation_ledgers = build_relation_label_ledgers(public_source_ledgers)
    public_relation_ledgers["projectodyssey"]["entries"] = []
    universe = build_simulated_full_accepted_run_universe(
        source_ledgers=public_source_ledgers,
        relation_label_ledgers=public_relation_ledgers,
    )
    contributors = scope_run_records(
        universe,
        scenario_ids=["projectodyssey"],
        variant_ids=["recallpack"],
    )
    aggregate = build_aggregate_report(
        universe["manifest"],
        claim_id="claim_false_supersession",
        claim_type="false_supersession_rate",
        run_records=contributors,
        run_ids=[run["run_id"] for run in contributors],
        adverse_run_ids=[],
        scope=build_aggregate_scope(
            contributors,
            designation="headline",
            scenario_ids=["projectodyssey"],
            variant_ids=["recallpack"],
        ),
        metrics=[
            {
                "metric_id": "false_supersession_rate",
                "n": 0,
                "numerator": 0,
                "denominator": 0,
                "rate": None,
            }
        ],
    )
    universe["contributors"] = contributors
    universe["aggregate"] = aggregate
    return universe


def build_test_only_simulated_cross_scenario_false_supersession_conflict_packet(
) -> dict[str, object]:
    source_ledgers = build_source_ledgers()
    project_refs = source_ledgers["projectodyssey"]["entries"]
    for index, entry in enumerate(source_ledgers["deepagents"]["entries"]):
        entry["source_ref"] = project_refs[index]["source_ref"]
    relation_ledgers = build_relation_label_ledgers(source_ledgers)
    project_entry = relation_ledgers["projectodyssey"]["entries"][0]
    deepagents_entry = relation_ledgers["deepagents"]["entries"][0]
    deepagents_entry["opportunity_id"] = project_entry["opportunity_id"]
    deepagents_entry["relation_kind"] = project_entry["relation_kind"]
    deepagents_entry["prior_source_ref"] = project_entry["prior_source_ref"]
    deepagents_entry["candidate_source_ref"] = project_entry["candidate_source_ref"]
    universe = build_simulated_full_accepted_run_universe(
        source_ledgers=source_ledgers,
        relation_label_ledgers=relation_ledgers,
    )
    _align_selected_sources(universe)
    universe["artifact_bytes"] = build_artifact_bytes(
        universe["manifest"],
        source_ledgers=universe["all_source_ledgers"],
        simulated_external_holdout=universe["simulated_external_holdout"],
        run_records=universe["all_runs"],
    )
    contributors = scope_run_records(
        universe,
        scenario_ids=["projectodyssey", "deepagents"],
        variant_ids=["recallpack"],
    )
    universe["contributors"] = contributors
    universe["aggregate"] = build_aggregate_report(
        universe["manifest"],
        claim_id="claim_false_supersession",
        claim_type="false_supersession_rate",
        run_records=contributors,
        run_ids=[run["run_id"] for run in contributors],
        adverse_run_ids=[],
        scope=build_aggregate_scope(
            contributors,
            designation="headline",
            scenario_ids=["projectodyssey", "deepagents"],
            variant_ids=["recallpack"],
        ),
        metrics=[
            {
                "metric_id": "false_supersession_rate",
                "n": 3,
                "numerator": 0,
                "denominator": 3,
                "rate": 0.0,
            }
        ],
    )
    universe["retained_attempt_authority"] = build_test_only_retained_attempt_authority(
        universe["manifest"],
        universe["all_runs"],
    )
    universe["retained_attempt_loader"] = build_test_only_retained_attempt_loader(
        universe["manifest"],
        universe["all_runs"],
    )
    return universe


def build_test_only_simulated_valid_manifest_red_packet() -> dict[str, object]:
    source_ledgers = build_source_ledgers()
    relation_label_ledgers = build_relation_label_ledgers(source_ledgers)
    simulated_external_holdout = build_simulated_external_holdout_bundle()
    manifest = build_full_execution_manifest(
        source_ledgers=source_ledgers,
        relation_label_ledgers=relation_label_ledgers,
        simulated_external_holdout=simulated_external_holdout,
    )
    run = build_evaluation_run(manifest)
    aggregate = build_aggregate_report(
        manifest,
        run_records=[run],
        adverse_run_ids=[],
    )
    evidence = build_evidence_manifest(
        manifest,
        run_records=[run],
        aggregate_records=[aggregate],
    )
    artifact_bytes = build_artifact_bytes(
        manifest,
        source_ledgers=source_ledgers,
        simulated_external_holdout=simulated_external_holdout,
        run_records=[run],
        aggregate_records=[aggregate],
        evidence_manifest=evidence,
    )
    return {
        "manifest": manifest,
        "source_ledgers": source_ledgers,
        "relation_label_ledgers": relation_label_ledgers,
        "simulated_external_holdout": simulated_external_holdout,
        "test_only_simulation_marker": simulated_external_holdout["custody_kind"],
        "run": run,
        "aggregate": aggregate,
        "evidence": evidence,
        "artifact_bytes": artifact_bytes,
    }
