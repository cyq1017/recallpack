from __future__ import annotations

import json
from collections import defaultdict
from typing import Any, Mapping

from recallpack.budget import canonical_json
from recallpack.evidence_common import (
    _escape_json_pointer,
    _raise_validation_errors,
    _schema_errors,
    _sha256_hex,
)
from recallpack.evidence_authority import load_finalized_attempt_snapshot
from recallpack.evidence_custody import validate_descendant_binding
from recallpack.evidence_execution_manifest import (
    validate_execution_manifest,
    validate_legacy_execution_manifest_diagnostic,
)
from recallpack.evidence_review_protocol import (
    ManifestRegistry,
    _fail,
    validate_registered_execution_manifest_41,
)
from recallpack.evidence_run import (
    validate_evaluation_run,
    validate_legacy_evaluation_run_diagnostic,
)
from recallpack.review_json import execution_manifest_sha256


_FINALIZATION_STATES = frozenset(
    {
        "accepted",
        "retained_non_authoritative",
        "invalidated_technical",
        "invalidated_abort",
    }
)
_CLAIM_METRICS = {
    "structural_runtime": frozenset(
        {
            "runtime_contract_success",
            "stale_leakage_rate",
            "active_memory_recall_at_budget",
            "supersession_prior_candidate_recall_at_8",
        }
    ),
    "downstream_superiority": frozenset({"downstream_full_suite_success"}),
    "false_supersession_rate": frozenset({"false_supersession_rate"}),
}


def validate_aggregate_report(
    report: Mapping[str, Any],
    *,
    execution_manifest: Mapping[str, Any],
    retained_attempt_loader: Any,
    artifact_bytes: Mapping[str, bytes],
    source_ledgers: Mapping[str, Mapping[str, Any]],
    relation_label_ledgers: Mapping[str, Mapping[str, Any]],
    manifest_registry: ManifestRegistry | None = None,
) -> None:
    _validate_aggregate_report_semantics(
        report,
        execution_manifest=execution_manifest,
        retained_attempt_loader=retained_attempt_loader,
        artifact_bytes=artifact_bytes,
        source_ledgers=source_ledgers,
        relation_label_ledgers=relation_label_ledgers,
        manifest_registry=manifest_registry,
        diagnostic_legacy=False,
    )


def validate_legacy_aggregate_report_diagnostic(
    report: Mapping[str, Any],
    *,
    execution_manifest: Mapping[str, Any],
    retained_attempt_loader: Any,
    artifact_bytes: Mapping[str, bytes],
    source_ledgers: Mapping[str, Mapping[str, Any]],
    relation_label_ledgers: Mapping[str, Mapping[str, Any]],
) -> None:
    """Exercise historical 4.0 aggregate semantics without admitting claims."""

    if not (
        execution_manifest.get("semantic_rules_version") == "4.0"
        and execution_manifest.get("descope_rung") in {"Full", "R1", "R2"}
    ):
        _fail(
            "legacy_diagnostic_manifest_required",
            "/descope_rung",
            "diagnostic aggregate validator accepts only historical 4.0 non-Floor manifests",
        )
    _validate_aggregate_report_semantics(
        report,
        execution_manifest=execution_manifest,
        retained_attempt_loader=retained_attempt_loader,
        artifact_bytes=artifact_bytes,
        source_ledgers=source_ledgers,
        relation_label_ledgers=relation_label_ledgers,
        manifest_registry=None,
        diagnostic_legacy=True,
    )


def _validate_aggregate_report_semantics(
    report: Mapping[str, Any],
    *,
    execution_manifest: Mapping[str, Any],
    retained_attempt_loader: Any,
    artifact_bytes: Mapping[str, bytes],
    source_ledgers: Mapping[str, Mapping[str, Any]],
    relation_label_ledgers: Mapping[str, Mapping[str, Any]],
    manifest_registry: ManifestRegistry | None,
    diagnostic_legacy: bool,
) -> None:
    schema_errors = [
        ("invalid_aggregate", pointer, detail)
        for _code, pointer, detail in _schema_errors(
            report,
            "aggregate",
            default_code="invalid_aggregate",
        )
    ]
    _raise_validation_errors(schema_errors)

    if diagnostic_legacy:
        validate_legacy_execution_manifest_diagnostic(
            execution_manifest,
            artifact_bytes=artifact_bytes,
            source_ledgers=source_ledgers,
        )
    else:
        if execution_manifest.get("semantic_rules_version") == "4.1":
            if manifest_registry is None:
                _fail(
                    "invalid_manifest_binding",
                    "/execution_manifest_sha256",
                    "4.1 aggregate validation requires the manifest registry",
                )
            validate_registered_execution_manifest_41(
                execution_manifest,
                artifact_bytes=artifact_bytes,
                registry=manifest_registry,
            )
            validate_descendant_binding(report, execution_manifest, manifest_registry)
        else:
            validate_execution_manifest(
                execution_manifest,
                artifact_bytes=artifact_bytes,
                source_ledgers=source_ledgers,
            )
    manifest_hash = execution_manifest_sha256(execution_manifest)
    _raise_validation_errors(
        _validate_revealed_holdout_ledgers(
            execution_manifest,
            artifact_bytes,
            source_ledgers,
        )
    )
    snapshot = _load_snapshot(retained_attempt_loader, manifest_hash)
    retained = _authenticate_retained_population(
        snapshot,
        execution_manifest=execution_manifest,
        manifest_hash=manifest_hash,
        artifact_bytes=artifact_bytes,
        source_ledgers=source_ledgers,
        relation_label_ledgers=relation_label_ledgers,
        manifest_registry=manifest_registry,
        diagnostic_legacy=diagnostic_legacy,
    )
    accepted = _derive_accepted_universe(retained, execution_manifest)

    errors: list[tuple[str, str, str]] = []
    errors.extend(_validate_report_binding(report, execution_manifest, manifest_hash))
    contributors = _scope_projection(report, accepted, execution_manifest, errors)
    errors.extend(_validate_run_sets(report, contributors))
    errors.extend(_validate_artifact_hashes(report, contributors, manifest_hash))
    errors.extend(
        _validate_metric(report, contributors, retained, execution_manifest)
    )
    _raise_validation_errors(errors)


def _validate_revealed_holdout_ledgers(
    manifest: Mapping[str, Any],
    artifact_bytes: Mapping[str, bytes],
    source_ledgers: Mapping[str, Mapping[str, Any]],
) -> list[tuple[str, str, str]]:
    errors: list[tuple[str, str, str]] = []
    scenarios = manifest.get("evidence_scenarios")
    if not isinstance(scenarios, list):
        return errors
    for scenario in scenarios:
        if (
            not isinstance(scenario, Mapping)
            or scenario.get("evidence_class") != "blind_holdout"
        ):
            continue
        scenario_id = scenario.get("scenario_slot")
        ledger = source_ledgers.get(scenario_id)
        artifact_id = scenario.get("source_ledger_artifact_id")
        frozen_payload = (
            artifact_bytes.get(artifact_id) if isinstance(artifact_id, str) else None
        )
        try:
            frozen_hash = bytes(frozen_payload).decode("utf-8", errors="strict").strip()
        except (TypeError, UnicodeDecodeError):
            frozen_hash = None
        revealed_hash = (
            _sha256_hex(canonical_json(ledger).encode("utf-8"))
            if isinstance(ledger, Mapping)
            else None
        )
        if revealed_hash != frozen_hash:
            errors.append(
                (
                    "invalid_aggregate",
                    f"/source_ledgers/{_escape_json_pointer(str(scenario_id))}",
                    "revealed blind holdout source ledger must match the frozen source_ledger_hash",
                )
            )
    return errors


def _load_snapshot(loader: Any, manifest_hash: str) -> Mapping[str, Any]:
    try:
        snapshot = load_finalized_attempt_snapshot(loader, manifest_hash)
    except Exception as exc:  # trusted capability failures still fail closed
        _raise_validation_errors(
            [
                (
                    "invalid_aggregate",
                    "/retained_attempt_loader",
                    f"retained_attempt_loader failed evaluator-owned capability check: {type(exc).__name__}",
                )
            ]
        )
    if not isinstance(snapshot, Mapping):
        _raise_validation_errors(
            [
                (
                    "invalid_aggregate",
                    "/retained_attempt_authority",
                    "retained attempt authority snapshot must be a mapping",
                )
            ]
        )
    return snapshot


def _authenticate_retained_population(
    snapshot: Mapping[str, Any],
    *,
    execution_manifest: Mapping[str, Any],
    manifest_hash: str,
    artifact_bytes: Mapping[str, bytes],
    source_ledgers: Mapping[str, Mapping[str, Any]],
    relation_label_ledgers: Mapping[str, Mapping[str, Any]],
    manifest_registry: ManifestRegistry | None = None,
    diagnostic_legacy: bool = False,
) -> list[dict[str, Any]]:
    errors: list[tuple[str, str, str]] = []
    entries = snapshot.get("entries")
    authority_kind = snapshot.get("authority_kind")
    simulation_marker = snapshot.get("simulation_marker")
    if authority_kind == "test_only_sealed_retained_attempt_authority":
        if simulation_marker != "test_only_sealed_retained_attempt_authority":
            errors.append(
                (
                    "invalid_aggregate",
                    "/retained_attempt_authority/simulation_marker",
                    "test-only retained authority requires its simulation marker",
                )
            )
    elif authority_kind == "production_append_only_attempt_journal":
        if simulation_marker is not None:
            errors.append(
                (
                    "invalid_aggregate",
                    "/retained_attempt_authority/simulation_marker",
                    "production retained authority cannot carry a simulation marker",
                )
            )
    else:
        errors.append(
            (
                "invalid_aggregate",
                "/retained_attempt_authority/authority_kind",
                "retained attempt authority kind is unsupported",
            )
        )
    if snapshot.get("authority_state") != "finalized":
        errors.append(
            (
                "invalid_aggregate",
                "/retained_attempt_authority/authority_state",
                "retained attempt authority snapshot must be finalized",
            )
        )
    if snapshot.get("execution_manifest_sha256") != manifest_hash:
        errors.append(
            (
                "invalid_aggregate",
                "/retained_attempt_authority/execution_manifest_sha256",
                "retained attempt authority must bind the aggregate execution manifest",
            )
        )
    if not isinstance(entries, list):
        errors.append(
            (
                "invalid_aggregate",
                "/retained_attempt_authority/entries",
                "retained attempt authority entries must be a list",
            )
        )
        _raise_validation_errors(errors)
    if snapshot.get("entry_count") != len(entries):
        errors.append(
            (
                "invalid_aggregate",
                "/retained_attempt_authority/entry_count",
                "entry_count must match the retained entry set",
            )
        )
    population_hash = _sha256_hex(canonical_json(entries).encode("utf-8"))
    if snapshot.get("population_sha256") != population_hash:
        errors.append(
            (
                "invalid_aggregate",
                "/retained_attempt_authority/population_sha256",
                "retained_attempt_authority population_sha256 must match the finalized retained entry set",
            )
        )
    orders = [
        entry.get("registration_order")
        for entry in entries
        if isinstance(entry, Mapping)
    ]
    if (
        len(orders) != len(entries)
        or any(not isinstance(order, int) for order in orders)
        or sorted(orders) != list(range(len(entries)))
    ):
        errors.append(
            (
                "invalid_aggregate",
                "/retained_attempt_authority/entries",
                "registration_order must be unique and contiguous from 0",
            )
        )

    retained: list[dict[str, Any]] = []
    seen_artifact_ids, seen_run_ids, seen_run_hashes = set(), set(), set()
    seen_slot_attempts: set[tuple[Any, Any]] = set()
    for index, entry in enumerate(entries):
        pointer = f"/retained_attempt_authority/entries/{index}"
        if not isinstance(entry, Mapping):
            errors.append(
                (
                    "invalid_aggregate",
                    pointer,
                    "retained authority entry must be a mapping",
                )
            )
            continue
        identities = (
            (entry.get("run_artifact_id"), seen_artifact_ids),
            (entry.get("run_id"), seen_run_ids),
            (entry.get("canonical_run_sha256"), seen_run_hashes),
            ((entry.get("slot_index"), entry.get("attempt_no")), seen_slot_attempts),
        )
        duplicate_identity = False
        for identity, seen in identities:
            try:
                if identity in seen:
                    duplicate_identity = True
                seen.add(identity)
            except TypeError:
                duplicate_identity = True
        if duplicate_identity:
            errors.append(
                (
                    "invalid_aggregate",
                    pointer,
                    "retained attempt identity must be unique across finalized authority entries",
                )
            )
        resolved = _resolve_retained_run(entry, pointer, artifact_bytes, errors)
        if resolved is None:
            continue
        run, canonical_hash = resolved
        errors.extend(_validate_authority_binding(entry, run, pointer, manifest_hash))
        if entry.get("finalization_state") not in _FINALIZATION_STATES:
            errors.append(
                (
                    "invalid_aggregate",
                    f"{pointer}/finalization_state",
                    "retained attempt finalization_state is unsupported",
                )
            )
        errors.extend(_validate_finalization_designation(entry, run, pointer))
        source_ledger = source_ledgers.get(run.get("scenario_id"))
        if not isinstance(source_ledger, Mapping):
            errors.append(
                (
                    "invalid_aggregate",
                    f"{pointer}/run_artifact_id",
                    "retained run scenario must resolve to a source ledger",
                )
            )
            continue
        run_kwargs: dict[str, Any] = {
            "artifact_bytes": artifact_bytes,
            "source_ledger": source_ledger,
        }
        if (
            run.get("variant_id") == "recallpack"
            and run.get("designation") == "headline"
        ):
            ledger = relation_label_ledgers.get(run.get("scenario_id"))
            if isinstance(ledger, Mapping):
                run_kwargs["relation_label_ledger"] = ledger
        try:
            if diagnostic_legacy:
                validate_legacy_evaluation_run_diagnostic(
                    run,
                    execution_manifest,
                    **run_kwargs,
                )
            else:
                validate_evaluation_run(
                    run,
                    execution_manifest,
                    manifest_registry=manifest_registry,
                    **run_kwargs,
                )
        except ValueError as exc:
            errors.append(
                (
                    "invalid_aggregate",
                    f"{pointer}/run_artifact_id",
                    f"retained run failed semantic validation: {str(exc).splitlines()[0]}",
                )
            )
        retained.append(
            {
                "entry": dict(entry),
                "entry_index": index,
                "run": run,
                "canonical_hash": canonical_hash,
            }
        )
    errors.extend(_validate_retained_journal_transitions(retained))
    _raise_validation_errors(errors)
    return retained


def _validate_retained_journal_transitions(
    retained: list[dict[str, Any]],
) -> list[tuple[str, str, str]]:
    errors: list[tuple[str, str, str]] = []
    attempts_by_slot: dict[Any, list[dict[str, Any]]] = defaultdict(list)
    for record in retained:
        entry = record["entry"]
        attempts_by_slot[entry.get("slot_index")].append(record)

    for attempts in attempts_by_slot.values():
        attempts.sort(
            key=lambda record: (
                record["entry"].get("registration_order")
                if isinstance(record["entry"].get("registration_order"), int)
                else record["entry_index"]
            )
        )
        accepted_seen = False
        non_authoritative_before_acceptance = False
        pending_invalidation = False
        manual_abort_seen = False
        previous_attempt_no: int | None = None
        for record in attempts:
            entry = record["entry"]
            index = record["entry_index"]
            pointer = f"/retained_attempt_authority/entries/{index}"
            attempt_no = entry.get("attempt_no")
            state = entry.get("finalization_state")
            if manual_abort_seen:
                errors.append(
                    (
                        "invalid_aggregate",
                        f"{pointer}/finalization_state",
                        "manual-abort attempt cannot precede an accepted same-slot replacement",
                    )
                )
            if (
                previous_attempt_no is not None
                and isinstance(attempt_no, int)
                and attempt_no <= previous_attempt_no
            ):
                errors.append(
                    (
                        "invalid_aggregate",
                        f"{pointer}/attempt_no",
                        "same-slot retained attempt numbers must increase in journal order",
                    )
                )
            if accepted_seen and state in {
                "invalidated_technical",
                "invalidated_abort",
            }:
                errors.append(
                    (
                        "invalid_aggregate",
                        f"{pointer}/finalization_state",
                        "accepted retained attempt cannot be followed by a same-slot invalidation",
                    )
                )
            if pending_invalidation and state != "accepted":
                errors.append(
                    (
                        "invalid_aggregate",
                        f"{pointer}/finalization_state",
                        "an invalidated retained attempt requires an accepted replacement",
                    )
                )
            if state == "accepted" and non_authoritative_before_acceptance:
                errors.append(
                    (
                        "invalid_aggregate",
                        f"{pointer}/finalization_state",
                        "non-authoritative attempt cannot precede an accepted same-slot replacement",
                    )
                )
            if state == "accepted":
                accepted_seen = True
                pending_invalidation = False
            elif state == "invalidated_technical":
                pending_invalidation = True
            elif state == "invalidated_abort":
                manual_abort_seen = True
            elif state == "retained_non_authoritative" and not accepted_seen:
                non_authoritative_before_acceptance = True
            if isinstance(attempt_no, int):
                previous_attempt_no = attempt_no
    return errors


def _resolve_retained_run(
    entry: Mapping[str, Any],
    pointer: str,
    artifact_bytes: Mapping[str, bytes],
    errors: list[tuple[str, str, str]],
) -> tuple[dict[str, Any], str] | None:
    artifact_id = entry.get("run_artifact_id")
    payload = artifact_bytes.get(artifact_id) if isinstance(artifact_id, str) else None
    if not isinstance(payload, (bytes, bytearray)):
        errors.append(
            (
                "invalid_aggregate",
                f"{pointer}/run_artifact_id",
                "retained run artifact bytes must exist",
            )
        )
        return None
    try:
        run = json.loads(bytes(payload).decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        errors.append(
            (
                "invalid_aggregate",
                f"{pointer}/run_artifact_id",
                "retained run artifact must contain canonical JSON",
            )
        )
        return None
    if not isinstance(run, dict) or canonical_json(run).encode("utf-8") != bytes(
        payload
    ):
        errors.append(
            (
                "invalid_aggregate",
                f"{pointer}/run_artifact_id",
                "retained run artifact must contain canonical JSON",
            )
        )
        return None
    canonical_hash = _sha256_hex(bytes(payload))
    if entry.get("canonical_run_sha256") != canonical_hash:
        errors.append(
            (
                "invalid_aggregate",
                f"{pointer}/canonical_run_sha256",
                "retained run canonical hash must match immutable artifact bytes",
            )
        )
    expected_artifact_id = f"run_{run.get('run_id')}"
    if artifact_id != expected_artifact_id:
        errors.append(
            (
                "invalid_aggregate",
                f"{pointer}/run_artifact_id",
                "retained run artifact ID must bind the resolved run ID",
            )
        )
    return run, canonical_hash


def _validate_authority_binding(
    entry: Mapping[str, Any],
    run: Mapping[str, Any],
    pointer: str,
    manifest_hash: str,
) -> list[tuple[str, str, str]]:
    errors: list[tuple[str, str, str]] = []
    fields = ("run_id", "slot_index", "attempt_no", "designation")
    for field in fields:
        if entry.get(field) != run.get(field):
            errors.append(
                (
                    "invalid_aggregate",
                    f"{pointer}/{field}",
                    f"retained authority {field} must match the resolved run",
                )
            )
    if entry.get("execution_manifest_sha256") != manifest_hash:
        errors.append(
            (
                "invalid_aggregate",
                f"{pointer}/execution_manifest_sha256",
                "retained attempts must bind the aggregate execution_manifest_sha256",
            )
        )
    return errors


def _validate_finalization_designation(
    entry: Mapping[str, Any],
    run: Mapping[str, Any],
    pointer: str,
) -> list[tuple[str, str, str]]:
    state = entry.get("finalization_state")
    designation = run.get("designation")
    valid = (
        state in {"accepted", "retained_non_authoritative"}
        and designation in {"headline", "diagnostic"}
    ) or state == designation
    if valid or state not in _FINALIZATION_STATES:
        return []
    detail = "finalization_state must match the retained run designation"
    if state == "accepted" and designation in {
        "invalidated_technical",
        "invalidated_abort",
    }:
        detail = "invalidated retained attempts cannot enter the accepted-run universe"
    return [
        (
            "invalid_aggregate",
            f"{pointer}/finalization_state",
            detail,
        )
    ]


def _derive_accepted_universe(
    retained: list[dict[str, Any]],
    manifest: Mapping[str, Any],
) -> list[dict[str, Any]]:
    errors: list[tuple[str, str, str]] = []
    execution_order = manifest.get("execution_order")
    if not isinstance(execution_order, list):
        return []
    accepted_by_slot: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for record in retained:
        entry = record["entry"]
        run = record["run"]
        state = entry.get("finalization_state")
        if state != "accepted":
            continue
        index = record["entry_index"]
        if run.get("designation") in {"invalidated_technical", "invalidated_abort"}:
            errors.append(
                (
                    "invalid_aggregate",
                    f"/retained_attempt_authority/entries/{index}/finalization_state",
                    "invalidated retained attempts cannot enter the accepted-run universe",
                )
            )
            continue
        slot_index = run.get("slot_index")
        if isinstance(slot_index, int):
            accepted_by_slot[slot_index].append(record)

    accepted: list[dict[str, Any]] = []
    for slot_index, slot in enumerate(execution_order):
        occupants = accepted_by_slot.get(slot_index, [])
        if len(occupants) != 1:
            errors.append(
                (
                    "invalid_aggregate",
                    "/retained_attempt_authority/entries",
                    "exactly one accepted retained attempt must occupy each predeclared slot",
                )
            )
            continue
        occupant = occupants[0]
        if occupant["run"].get("designation") != slot.get("planned_designation"):
            errors.append(
                (
                    "invalid_aggregate",
                    f"/retained_attempt_authority/entries/{occupant['entry_index']}/designation",
                    "accepted retained attempt designation must match the predeclared slot",
                )
            )
        accepted.append(occupant)
    _raise_validation_errors(errors)
    return accepted


def _validate_report_binding(
    report: Mapping[str, Any],
    manifest: Mapping[str, Any],
    manifest_hash: str,
) -> list[tuple[str, str, str]]:
    errors: list[tuple[str, str, str]] = []
    if report.get("manifest_version") != manifest.get("manifest_version"):
        errors.append(
            (
                "invalid_aggregate",
                "/manifest_version",
                "aggregate manifest_version must match",
            )
        )
    if report.get("semantic_rules_version") != manifest.get("semantic_rules_version"):
        errors.append(
            (
                "invalid_aggregate",
                "/semantic_rules_version",
                "aggregate semantic rules must match",
            )
        )
    if report.get("execution_manifest_sha256") != manifest_hash:
        errors.append(
            (
                "invalid_aggregate",
                "/execution_manifest_sha256",
                "aggregate execution_manifest_sha256 must equal the canonical manifest hash",
            )
        )
    declarations = manifest.get("claim_declarations")
    matches = []
    if isinstance(declarations, list):
        matches = [
            declaration
            for declaration in declarations
            if isinstance(declaration, Mapping)
            and declaration.get("claim_id") == report.get("claim_id")
        ]
    if len(matches) != 1:
        errors.append(
            (
                "invalid_aggregate",
                "/claim_id",
                "claim_id must resolve to exactly one manifest claim declaration",
            )
        )
        return errors
    if report.get("claim_type") != matches[0].get("claim_type"):
        errors.append(
            (
                "invalid_aggregate",
                "/claim_type",
                "claim_type must equal the resolved manifest claim declaration",
            )
        )
    metric = report.get("metrics", [{}])[0]
    allowed = _CLAIM_METRICS.get(report.get("claim_type"), frozenset())
    if isinstance(metric, Mapping) and metric.get("metric_id") not in allowed:
        errors.append(
            (
                "invalid_aggregate",
                "/metrics/0/metric_id",
                "aggregate metric_id is incompatible with claim_type",
            )
        )
    return errors


def _scope_projection(
    report: Mapping[str, Any],
    accepted: list[dict[str, Any]],
    manifest: Mapping[str, Any],
    errors: list[tuple[str, str, str]],
) -> list[dict[str, Any]]:
    scope = report.get("scope")
    if not isinstance(scope, Mapping):
        return []
    scenarios = scope.get("scenario_ids")
    variants = scope.get("variant_ids")
    designation = scope.get("designation")
    execution_order = manifest.get("execution_order", [])
    known_scenarios = {
        slot.get("scenario_slot")
        for slot in execution_order
        if isinstance(slot, Mapping)
    }
    for index, scenario_id in enumerate(scenarios):
        if scenario_id not in known_scenarios:
            errors.append(
                (
                    "invalid_aggregate",
                    f"/scope/scenario_ids/{index}",
                    "scope scenario_ids must resolve to manifest execution slots",
                )
            )
    contributors = [
        record
        for record in accepted
        if record["run"].get("scenario_id") in scenarios
        and record["run"].get("variant_id") in variants
        and record["run"].get("designation") == designation
    ]
    if not contributors:
        errors.append(
            ("invalid_aggregate", "/scope", "aggregate scope must select accepted runs")
        )
    return contributors


def _validate_run_sets(
    report: Mapping[str, Any],
    contributors: list[dict[str, Any]],
) -> list[tuple[str, str, str]]:
    expected = [record["run"]["run_id"] for record in contributors]
    adverse = [
        record["run"]["run_id"]
        for record in contributors
        if record["run"].get("outcome", {}).get("status") == "adverse"
    ]
    errors: list[tuple[str, str, str]] = []
    if report.get("run_ids") != expected:
        pointer = "/run_ids"
        supplied = report.get("run_ids")
        if isinstance(supplied, list):
            for index, run_id in enumerate(supplied):
                if index >= len(expected) or run_id != expected[index]:
                    pointer = f"/run_ids/{index}"
                    break
        errors.append(
            (
                "invalid_aggregate",
                pointer,
                "run_ids must equal the accepted scope projection derived from retained_attempt_authority",
            )
        )
    if report.get("adverse_run_ids") != adverse:
        errors.append(
            (
                "invalid_aggregate",
                "/adverse_run_ids",
                "adverse_run_ids must equal the adverse contributing run subset",
            )
        )
    return errors


def _validate_artifact_hashes(
    report: Mapping[str, Any],
    contributors: list[dict[str, Any]],
    manifest_hash: str,
) -> list[tuple[str, str, str]]:
    supplied = report.get("artifact_hashes")
    expected = {"execution_manifest": manifest_hash}
    expected.update(
        {
            f"run:{record['run']['run_id']}": record["canonical_hash"]
            for record in contributors
        }
    )
    if not isinstance(supplied, Mapping) or set(supplied) != set(expected):
        return [
            (
                "invalid_aggregate",
                "/artifact_hashes",
                "artifact_hashes must contain exactly execution_manifest and contributing run hashes",
            )
        ]
    errors: list[tuple[str, str, str]] = []
    for key, value in expected.items():
        if supplied.get(key) != value:
            pointer = f"/artifact_hashes/{_escape_json_pointer(key)}"
            detail = "execution manifest hash must equal the canonical manifest hash"
            if key.startswith("run:"):
                detail = (
                    "contributing run hash must equal the canonical retained run hash"
                )
            errors.append(("invalid_aggregate", pointer, detail))
    return errors


def _validate_metric(
    report: Mapping[str, Any],
    contributors: list[dict[str, Any]],
    retained: list[dict[str, Any]],
    execution_manifest: Mapping[str, Any],
) -> list[tuple[str, str, str]]:
    metric = report["metrics"][0]
    metric_id = metric["metric_id"]
    if (
        execution_manifest.get("descope_rung") == "Floor"
        and metric_id != "runtime_contract_success"
    ):
        return [
            (
                "invalid_aggregate",
                "/metrics/0/metric_id",
                "Floor permits only evaluator-owned structural runtime arithmetic",
            )
        ]
    if metric_id == "false_supersession_rate":
        expected, conflict = _false_supersession_arithmetic(
            report, contributors, retained
        )
        if conflict:
            return [
                (
                    "invalid_aggregate",
                    "/metrics/0",
                    "false_supersession_rate must reject opportunity_id groups reused across scenarios",
                )
            ]
    else:
        expected = _ordinary_arithmetic(metric_id, contributors)
    if expected is None:
        return [
            (
                "invalid_aggregate",
                "/metrics/0/metric_id",
                "unsupported aggregate metric_id",
            )
        ]

    errors: list[tuple[str, str, str]] = []
    for field in ("n", "numerator", "denominator"):
        if metric.get(field) != expected[field]:
            detail = f"{metric_id} {field} must equal recomputed arithmetic"
            if metric_id == "false_supersession_rate" and field == "n":
                detail = "false_supersession_rate n must equal unique opportunity count"
            elif metric_id == "false_supersession_rate" and field == "numerator":
                detail = (
                    "false_supersession_rate numerator must include adverse retained "
                    "non-authoritative repeats"
                )
            errors.append(("invalid_aggregate", f"/metrics/0/{field}", detail))
    if metric.get("rate") != expected["rate"]:
        errors.append(
            (
                "invalid_aggregate",
                "/metrics/0/rate",
                f"{metric_id} rate must equal numerator divided by denominator and be null only at zero denominator",
            )
        )
    return errors


def _ordinary_arithmetic(
    metric_id: str,
    contributors: list[dict[str, Any]],
) -> dict[str, int | float | None] | None:
    runs = [record["run"] for record in contributors]
    if metric_id == "runtime_contract_success":
        n = len(runs)
        numerator = n
    elif metric_id == "stale_leakage_rate":
        n = sum(run["metrics"]["selected_total"] for run in runs)
        numerator = sum(run["metrics"]["stale_selected"] for run in runs)
    elif metric_id == "active_memory_recall_at_budget":
        n = sum(run["metrics"]["required_total"] for run in runs)
        numerator = sum(run["metrics"]["required_selected"] for run in runs)
    elif metric_id == "supersession_prior_candidate_recall_at_8":
        n = sum(run["metrics"]["candidate_prior_total"] for run in runs)
        numerator = sum(run["metrics"]["candidate_prior_selected"] for run in runs)
    elif metric_id == "downstream_full_suite_success":
        n = len(runs)
        numerator = sum(
            isinstance(run.get("test_result"), Mapping)
            and run["test_result"].get("full_suite_passed") is True
            for run in runs
        )
    else:
        return None
    return _arithmetic(n, numerator)


def _false_supersession_arithmetic(
    report: Mapping[str, Any],
    contributors: list[dict[str, Any]],
    retained: list[dict[str, Any]],
) -> tuple[dict[str, int | float | None], bool]:
    scope = report["scope"]
    relevant = [
        record["run"]
        for record in retained
        if record["run"].get("scenario_id") in scope["scenario_ids"]
        and record["run"].get("variant_id") == "recallpack"
        and record["run"].get("designation") == "headline"
    ]
    grouped: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    scenarios: dict[str, set[str]] = defaultdict(set)
    for run in relevant:
        for opportunity in run.get("relation_opportunities", []):
            opportunity_id = opportunity["opportunity_id"]
            grouped[opportunity_id].append(opportunity)
            scenarios[opportunity_id].add(run["scenario_id"])
    conflict = any(len(values) > 1 for values in scenarios.values())
    numerator = sum(
        any(
            opportunity.get("relation_kind") == "hard_negative"
            and opportunity.get("outcome") == "false_supersession"
            for opportunity in opportunities
        )
        for opportunities in grouped.values()
    )
    return _arithmetic(len(grouped), numerator), conflict


def _arithmetic(n: int, numerator: int) -> dict[str, int | float | None]:
    return {
        "n": n,
        "numerator": numerator,
        "denominator": n,
        "rate": None if n == 0 else numerator / n,
    }
