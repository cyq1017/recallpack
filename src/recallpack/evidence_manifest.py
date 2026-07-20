from __future__ import annotations

import json
from typing import Any, Mapping

from recallpack.budget import canonical_json
from recallpack.evidence_aggregate import (
    _authenticate_retained_population,
    _derive_accepted_universe,
    _load_snapshot,
    _validate_revealed_holdout_ledgers,
    validate_aggregate_report,
    validate_legacy_aggregate_report_diagnostic,
)
from recallpack.evidence_custody import validate_descendant_binding
from recallpack.evidence_authority import is_test_only_retained_attempt_loader
from recallpack.evidence_common import (
    _escape_json_pointer,
    _normalize_relative_path,
    _raise_validation_errors,
    _scan_text,
    _schema_errors,
    _sha256_hex,
    _validate_catalog_artifact,
)
from recallpack.evidence_execution_manifest import (
    validate_execution_manifest,
    validate_legacy_execution_manifest_diagnostic,
)
from recallpack.evidence_manifest_claims import validate_manifest_claims
from recallpack.evidence_review_protocol import (
    ManifestRegistry,
    _fail,
    validate_registered_execution_manifest_41,
)
from recallpack.review_json import execution_manifest_sha256


def validate_evidence_manifest(
    record: Mapping[str, Any],
    execution_manifest: Mapping[str, Any],
    *,
    retained_attempt_loader: Any,
    artifact_bytes: Mapping[str, bytes],
    source_ledgers: Mapping[str, Mapping[str, Any]],
    relation_label_ledgers: Mapping[str, Mapping[str, Any]],
    predecessor_manifest: Mapping[str, Any] | None = None,
    manifest_registry: ManifestRegistry | None = None,
) -> None:
    _validate_evidence_manifest_semantics(
        record,
        execution_manifest,
        retained_attempt_loader=retained_attempt_loader,
        artifact_bytes=artifact_bytes,
        source_ledgers=source_ledgers,
        relation_label_ledgers=relation_label_ledgers,
        predecessor_manifest=predecessor_manifest,
        manifest_registry=manifest_registry,
        diagnostic_legacy=False,
    )


def validate_legacy_evidence_manifest_diagnostic(
    record: Mapping[str, Any],
    execution_manifest: Mapping[str, Any],
    *,
    retained_attempt_loader: Any,
    artifact_bytes: Mapping[str, bytes],
    source_ledgers: Mapping[str, Mapping[str, Any]],
    relation_label_ledgers: Mapping[str, Mapping[str, Any]],
    predecessor_manifest: Mapping[str, Any] | None = None,
) -> None:
    """Exercise historical 4.0 evidence semantics without admitting claims."""

    if not (
        execution_manifest.get("semantic_rules_version") == "4.0"
        and execution_manifest.get("descope_rung") in {"Full", "R1", "R2"}
    ):
        _fail(
            "legacy_diagnostic_manifest_required",
            "/descope_rung",
            "diagnostic evidence validator accepts only historical 4.0 non-Floor manifests",
        )
    _validate_evidence_manifest_semantics(
        record,
        execution_manifest,
        retained_attempt_loader=retained_attempt_loader,
        artifact_bytes=artifact_bytes,
        source_ledgers=source_ledgers,
        relation_label_ledgers=relation_label_ledgers,
        predecessor_manifest=predecessor_manifest,
        manifest_registry=None,
        diagnostic_legacy=True,
    )


def _validate_evidence_manifest_semantics(
    record: Mapping[str, Any],
    execution_manifest: Mapping[str, Any],
    *,
    retained_attempt_loader: Any,
    artifact_bytes: Mapping[str, bytes],
    source_ledgers: Mapping[str, Mapping[str, Any]],
    relation_label_ledgers: Mapping[str, Mapping[str, Any]],
    predecessor_manifest: Mapping[str, Any] | None,
    manifest_registry: ManifestRegistry | None,
    diagnostic_legacy: bool,
) -> None:
    _raise_validation_errors(_evidence_schema_errors(record))
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
                    "4.1 evidence validation requires the manifest registry",
                )
            validate_registered_execution_manifest_41(
                execution_manifest,
                artifact_bytes=artifact_bytes,
                registry=manifest_registry,
            )
            validate_descendant_binding(record, execution_manifest, manifest_registry)
        else:
            validate_execution_manifest(
                execution_manifest,
                artifact_bytes=artifact_bytes,
                source_ledgers=source_ledgers,
            )
    manifest_hash = execution_manifest_sha256(execution_manifest)

    errors = _validate_manifest_binding(record, execution_manifest, manifest_hash)
    errors.extend(
        _remap_errors(
            _validate_revealed_holdout_ledgers(
                execution_manifest,
                artifact_bytes,
                source_ledgers,
            ),
            "incomplete_final_evidence",
        )
    )
    _raise_validation_errors(errors)

    catalog = record["output_artifact_catalog"]
    _raise_validation_errors(_validate_catalog(catalog, artifact_bytes))
    retained, retained_snapshot = _load_retained_population(
        retained_attempt_loader,
        manifest_hash=manifest_hash,
        execution_manifest=execution_manifest,
        artifact_bytes=artifact_bytes,
        source_ledgers=source_ledgers,
        relation_label_ledgers=relation_label_ledgers,
        manifest_registry=manifest_registry,
        diagnostic_legacy=diagnostic_legacy,
    )
    accepted = _derive_accepted_or_fail(retained, execution_manifest)
    _raise_validation_errors(_validate_run_completeness(record, retained))

    runs, run_errors = _resolve_runs(record, retained, catalog, artifact_bytes)
    aggregates, aggregate_errors = _resolve_aggregates(
        record,
        catalog,
        artifact_bytes,
    )
    _raise_validation_errors(run_errors + aggregate_errors)
    _raise_validation_errors(
        _validate_catalog_closure(record, catalog, runs, aggregates)
    )
    _raise_validation_errors(
        _validate_chain(record, predecessor_manifest, manifest_hash)
    )
    if predecessor_manifest is not None:
        _validate_predecessor_record(
            predecessor_manifest,
            execution_manifest=execution_manifest,
            retained_attempt_loader=retained_attempt_loader,
            artifact_bytes=artifact_bytes,
            source_ledgers=source_ledgers,
            relation_label_ledgers=relation_label_ledgers,
            retained=retained,
            accepted=accepted,
            manifest_registry=manifest_registry,
            diagnostic_legacy=diagnostic_legacy,
        )
    _raise_validation_errors(
        _validate_aggregate_completeness(record, execution_manifest, aggregates)
    )

    for aggregate in aggregates:
        try:
            aggregate_validator = (
                validate_legacy_aggregate_report_diagnostic
                if diagnostic_legacy
                else validate_aggregate_report
            )
            aggregate_validator(
                aggregate,
                execution_manifest=execution_manifest,
                retained_attempt_loader=retained_attempt_loader,
                artifact_bytes=artifact_bytes,
                source_ledgers=source_ledgers,
                relation_label_ledgers=relation_label_ledgers,
                **(
                    {}
                    if diagnostic_legacy
                    else {"manifest_registry": manifest_registry}
                ),
            )
        except ValueError as exc:
            _raise_validation_errors(
                [
                    (
                        "incomplete_final_evidence",
                        f"/aggregate_ids/{_escape_json_pointer(str(aggregate.get('aggregate_id')))}",
                        f"aggregate failed independent validation: {str(exc).splitlines()[0]}",
                    )
                ]
            )

    aggregates_by_claim = {
        aggregate["claim_id"]: aggregate for aggregate in aggregates
    }
    _raise_validation_errors(
        validate_manifest_claims(
            record,
            execution_manifest,
            aggregates_by_claim=aggregates_by_claim,
            retained=retained,
            accepted=accepted,
        )
    )
    if (
        record.get("status") == "final"
        and (
            is_test_only_retained_attempt_loader(retained_attempt_loader)
            or retained_snapshot.get("simulation_marker") is not None
        )
    ):
        _raise_validation_errors(
            [
                (
                    "incomplete_final_evidence",
                    "/status",
                    "test simulation authority cannot validate final evidence",
                )
            ]
        )


def _evidence_schema_errors(value: Any) -> list[tuple[str, str, str]]:
    errors = []
    for _code, pointer, detail in _schema_errors(
        value,
        "evidenceManifest",
        default_code="incomplete_final_evidence",
    ):
        code = "incomplete_final_evidence"
        if pointer.startswith("/output_artifact_catalog"):
            code = "invalid_output_catalog"
        elif pointer.startswith("/claims"):
            code = "invalid_claim_reference"
        elif pointer.startswith("/previous_evidence_manifest_sha256"):
            code = "invalid_manifest_chain"
        errors.append((code, pointer, detail))
    return errors


def _validate_manifest_binding(
    record: Mapping[str, Any],
    manifest: Mapping[str, Any],
    manifest_hash: str,
) -> list[tuple[str, str, str]]:
    errors = []
    if record.get("semantic_rules_version") != manifest.get("semantic_rules_version"):
        errors.append(
            (
                "incomplete_final_evidence",
                "/semantic_rules_version",
                "evidence semantic rules must match the execution manifest",
            )
        )
    if record.get("execution_manifest_version") != manifest.get("manifest_version"):
        errors.append(
            (
                "incomplete_final_evidence",
                "/execution_manifest_version",
                "evidence manifest version must match the execution manifest",
            )
        )
    if record.get("execution_manifest_sha256") != manifest_hash:
        errors.append(
            (
                "incomplete_final_evidence",
                "/execution_manifest_sha256",
                "evidence manifest hash must bind the canonical execution manifest",
            )
        )
    return errors


def _load_retained_population(
    loader: Any,
    *,
    manifest_hash: str,
    execution_manifest: Mapping[str, Any],
    artifact_bytes: Mapping[str, bytes],
    source_ledgers: Mapping[str, Mapping[str, Any]],
    relation_label_ledgers: Mapping[str, Mapping[str, Any]],
    manifest_registry: ManifestRegistry | None = None,
    diagnostic_legacy: bool = False,
) -> tuple[list[dict[str, Any]], Mapping[str, Any]]:
    try:
        snapshot = _load_snapshot(loader, manifest_hash)
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
        return retained, snapshot
    except ValueError as exc:
        _raise_validation_errors(
            [
                (
                    "incomplete_final_evidence",
                    "/retained_attempt_loader",
                    f"trusted retained population is invalid: {str(exc).splitlines()[0]}",
                )
            ]
        )
    raise AssertionError("unreachable")


def _derive_accepted_or_fail(
    retained: list[dict[str, Any]],
    manifest: Mapping[str, Any],
) -> list[dict[str, Any]]:
    try:
        return _derive_accepted_universe(retained, manifest)
    except ValueError as exc:
        _raise_validation_errors(
            [
                (
                    "incomplete_final_evidence",
                    "/retained_attempt_loader",
                    f"accepted retained population is invalid: {str(exc).splitlines()[0]}",
                )
            ]
        )
    raise AssertionError("unreachable")


def _validate_run_completeness(
    record: Mapping[str, Any],
    retained: list[dict[str, Any]],
) -> list[tuple[str, str, str]]:
    reported = set(record.get("run_ids", []))
    complete = {item["run"]["run_id"] for item in retained}
    valid = reported == complete if record.get("status") == "final" else reported <= complete
    if valid:
        return []
    return [
        (
            "incomplete_final_evidence",
            "/run_ids",
            "run IDs must equal the retained population for final records and be a subset for partial records",
        )
    ]


def _validate_catalog(
    catalog: Mapping[str, Any],
    artifact_bytes: Mapping[str, bytes],
) -> list[tuple[str, str, str]]:
    errors = []
    seen_paths: set[str] = set()
    for artifact_id, metadata in catalog.items():
        pointer = f"/output_artifact_catalog/{_escape_json_pointer(artifact_id)}"
        relative_path = metadata.get("relative_path")
        if isinstance(relative_path, str):
            normalized = _normalize_relative_path(relative_path)
            if normalized != relative_path:
                errors.append(
                    (
                        "invalid_output_catalog",
                        f"{pointer}/relative_path",
                        "relative_path must be normalized",
                    )
                )
            if normalized in seen_paths:
                errors.append(
                    (
                        "invalid_output_catalog",
                        f"{pointer}/relative_path",
                        "relative_path must be unique",
                    )
                )
            else:
                seen_paths.add(normalized)
            errors.extend(
                _remap_errors(
                    _scan_text(relative_path, f"{pointer}/relative_path"),
                    "invalid_output_catalog",
                )
            )
        errors.extend(
            _remap_errors(
                _validate_catalog_artifact(
                    artifact_id,
                    metadata,
                    artifact_bytes,
                    pointer,
                ),
                "invalid_output_catalog",
            )
        )
    return errors


def _resolve_runs(
    record: Mapping[str, Any],
    retained: list[dict[str, Any]],
    catalog: Mapping[str, Any],
    artifact_bytes: Mapping[str, bytes],
) -> tuple[list[dict[str, Any]], list[tuple[str, str, str]]]:
    retained_by_id = {item["run"]["run_id"]: item["run"] for item in retained}
    runs = []
    errors = []
    for index, run_id in enumerate(record.get("run_ids", [])):
        artifact_id = f"run_{run_id}"
        run, parse_errors = _resolve_json_artifact(
            artifact_id,
            "evaluation_run",
            catalog,
            artifact_bytes,
            f"/run_ids/{index}",
        )
        errors.extend(parse_errors)
        if run is None:
            continue
        if run.get("run_id") != run_id or run != retained_by_id.get(run_id):
            errors.append(
                (
                    "invalid_output_catalog",
                    f"/run_ids/{index}",
                    "listed run must equal its authenticated retained artifact",
                )
            )
            continue
        runs.append(run)
        embedded = run.get("run_output_artifact_catalog", {})
        for embedded_id, metadata in embedded.items():
            if catalog.get(embedded_id) != metadata:
                errors.append(
                    (
                        "invalid_output_catalog",
                        f"/output_artifact_catalog/{_escape_json_pointer(embedded_id)}",
                        "embedded run output metadata must appear byte-for-byte in the evidence catalog",
                    )
                )
    return runs, errors


def _resolve_aggregates(
    record: Mapping[str, Any],
    catalog: Mapping[str, Any],
    artifact_bytes: Mapping[str, bytes],
) -> tuple[list[dict[str, Any]], list[tuple[str, str, str]]]:
    aggregates = []
    errors = []
    for index, aggregate_id in enumerate(record.get("aggregate_ids", [])):
        aggregate, parse_errors = _resolve_json_artifact(
            aggregate_id,
            "aggregate_report",
            catalog,
            artifact_bytes,
            f"/aggregate_ids/{index}",
        )
        errors.extend(parse_errors)
        if aggregate is None:
            continue
        if aggregate.get("aggregate_id") != aggregate_id:
            errors.append(
                (
                    "invalid_output_catalog",
                    f"/aggregate_ids/{index}",
                    "aggregate content ID must match its catalog ID",
                )
            )
        aggregates.append(aggregate)
    return aggregates, errors


def _resolve_json_artifact(
    artifact_id: str,
    expected_kind: str,
    catalog: Mapping[str, Any],
    artifact_bytes: Mapping[str, bytes],
    pointer: str,
) -> tuple[dict[str, Any] | None, list[tuple[str, str, str]]]:
    metadata = catalog.get(artifact_id)
    if not isinstance(metadata, Mapping) or metadata.get("kind") != expected_kind:
        return None, [
            (
                "invalid_output_catalog",
                pointer,
                f"artifact must resolve to output kind {expected_kind}",
            )
        ]
    payload = artifact_bytes.get(artifact_id)
    if not isinstance(payload, (bytes, bytearray)):
        return None, [("invalid_output_catalog", pointer, "artifact bytes must exist")]
    try:
        value = json.loads(bytes(payload).decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None, [("invalid_output_catalog", pointer, "artifact must be JSON")]
    if not isinstance(value, dict) or canonical_json(value).encode("utf-8") != bytes(
        payload
    ):
        return None, [
            (
                "invalid_output_catalog",
                pointer,
                "artifact must contain canonical JSON",
            )
        ]
    return value, []


def _validate_catalog_closure(
    record: Mapping[str, Any],
    catalog: Mapping[str, Any],
    runs: list[dict[str, Any]],
    aggregates: list[dict[str, Any]],
) -> list[tuple[str, str, str]]:
    expected = {f"run_{run['run_id']}" for run in runs}
    expected.update(aggregate["aggregate_id"] for aggregate in aggregates)
    for run in runs:
        expected.update(run.get("run_output_artifact_catalog", {}))
    if set(catalog) == expected:
        return []
    return [
        (
            "invalid_output_catalog",
            "/output_artifact_catalog",
            "output catalog must exactly close listed runs, aggregates, and embedded run outputs",
        )
    ]


def _validate_chain(
    record: Mapping[str, Any],
    predecessor: Mapping[str, Any] | None,
    manifest_hash: str,
) -> list[tuple[str, str, str]]:
    pointer = record.get("previous_evidence_manifest_sha256")
    if predecessor is None:
        if pointer is None:
            return []
        return [
            (
                "invalid_manifest_chain",
                "/previous_evidence_manifest_sha256",
                "a predecessor hash requires the predecessor manifest",
            )
        ]

    errors = _evidence_schema_errors(predecessor)
    if errors:
        return [
            (
                "invalid_manifest_chain",
                "/predecessor_manifest",
                "predecessor manifest must be schema-valid",
            )
        ]
    if pointer != _sha256_hex(canonical_json(predecessor).encode("utf-8")):
        errors.append(
            (
                "invalid_manifest_chain",
                "/previous_evidence_manifest_sha256",
                "predecessor hash must equal canonical predecessor bytes",
            )
        )
    if predecessor.get("status") != "partial":
        errors.append(
            (
                "invalid_manifest_chain",
                "/predecessor_manifest/status",
                "final evidence manifests are terminal and cannot be predecessors",
            )
        )
    if predecessor.get("execution_manifest_sha256") != manifest_hash:
        errors.append(
            (
                "invalid_manifest_chain",
                "/predecessor_manifest/execution_manifest_sha256",
                "predecessor must bind the same execution manifest",
            )
        )
    for field in ("run_ids", "aggregate_ids"):
        if not set(predecessor.get(field, [])) <= set(record.get(field, [])):
            errors.append(
                (
                    "invalid_manifest_chain",
                    f"/predecessor_manifest/{field}",
                    f"predecessor {field} must be an unchanged successor subset",
                )
            )
    predecessor_catalog = predecessor.get("output_artifact_catalog", {})
    successor_catalog = record.get("output_artifact_catalog", {})
    if any(successor_catalog.get(key) != value for key, value in predecessor_catalog.items()):
        errors.append(
            (
                "invalid_manifest_chain",
                "/predecessor_manifest/output_artifact_catalog",
                "predecessor outputs must be byte-identical successor subsets",
            )
        )
    return errors


def _validate_aggregate_completeness(
    record: Mapping[str, Any],
    manifest: Mapping[str, Any],
    aggregates: list[dict[str, Any]],
) -> list[tuple[str, str, str]]:
    if record.get("status") == "partial":
        declared = {item["claim_id"] for item in manifest.get("claim_declarations", [])}
        if all(aggregate.get("claim_id") in declared for aggregate in aggregates):
            return []
    else:
        declared = [item["claim_id"] for item in manifest.get("claim_declarations", [])]
        reported = [aggregate.get("claim_id") for aggregate in aggregates]
        if len(reported) == len(set(reported)) and set(reported) == set(declared):
            return []
    return [
        (
            "incomplete_final_evidence",
            "/aggregate_ids",
            "final aggregates must map one-to-one to declarations; partial aggregates must reference declarations",
        )
    ]


def _validate_predecessor_record(
    predecessor: Mapping[str, Any],
    *,
    execution_manifest: Mapping[str, Any],
    retained_attempt_loader: Any,
    artifact_bytes: Mapping[str, bytes],
    source_ledgers: Mapping[str, Mapping[str, Any]],
    relation_label_ledgers: Mapping[str, Mapping[str, Any]],
    retained: list[dict[str, Any]],
    accepted: list[dict[str, Any]],
    manifest_registry: ManifestRegistry | None,
    diagnostic_legacy: bool,
) -> None:
    try:
        manifest_hash = execution_manifest_sha256(execution_manifest)
        _raise_validation_errors(
            _validate_manifest_binding(
                predecessor,
                execution_manifest,
                manifest_hash,
            )
        )
        catalog = predecessor["output_artifact_catalog"]
        _raise_validation_errors(_validate_catalog(catalog, artifact_bytes))
        _raise_validation_errors(_validate_run_completeness(predecessor, retained))
        runs, run_errors = _resolve_runs(
            predecessor,
            retained,
            catalog,
            artifact_bytes,
        )
        aggregates, aggregate_errors = _resolve_aggregates(
            predecessor,
            catalog,
            artifact_bytes,
        )
        _raise_validation_errors(run_errors + aggregate_errors)
        _raise_validation_errors(
            _validate_catalog_closure(predecessor, catalog, runs, aggregates)
        )
        _raise_validation_errors(
            _validate_aggregate_completeness(
                predecessor,
                execution_manifest,
                aggregates,
            )
        )
        for aggregate in aggregates:
            aggregate_validator = (
                validate_legacy_aggregate_report_diagnostic
                if diagnostic_legacy
                else validate_aggregate_report
            )
            aggregate_validator(
                aggregate,
                execution_manifest=execution_manifest,
                retained_attempt_loader=retained_attempt_loader,
                artifact_bytes=artifact_bytes,
                source_ledgers=source_ledgers,
                relation_label_ledgers=relation_label_ledgers,
                **(
                    {}
                    if diagnostic_legacy
                    else {"manifest_registry": manifest_registry}
                ),
            )
        aggregates_by_claim = {
            aggregate["claim_id"]: aggregate for aggregate in aggregates
        }
        _raise_validation_errors(
            validate_manifest_claims(
                predecessor,
                execution_manifest,
                aggregates_by_claim=aggregates_by_claim,
                retained=retained,
                accepted=accepted,
            )
        )
    except ValueError as exc:
        _raise_validation_errors(
            [
                (
                    "invalid_manifest_chain",
                    "/predecessor_manifest",
                    f"predecessor failed semantic validation: {str(exc).splitlines()[0]}",
                )
            ]
        )


def _remap_errors(
    errors: list[tuple[str, str, str]],
    code: str,
) -> list[tuple[str, str, str]]:
    return [(code, pointer, detail) for _old_code, pointer, detail in errors]
