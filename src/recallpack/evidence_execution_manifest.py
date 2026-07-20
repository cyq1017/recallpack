from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import Any, Mapping

from recallpack.budget import canonical_json
from recallpack.evidence_common import (
    _FROM_RE,
    _OUTPUT_ONLY_INPUT_KINDS,
    _V4_VARIANTS,
    _parse_json_payload,
    _raise_validation_errors,
    _resolve_artifact,
    _schema_errors,
    _scan_text,
    _validate_catalog_artifact,
    _normalize_relative_path,
)


def validate_execution_manifest(
    manifest: Mapping[str, Any],
    *,
    artifact_bytes: Mapping[str, bytes],
    source_ledgers: Mapping[str, Mapping[str, Any]] | None = None,
    repository_root: Path | None = None,
) -> None:
    if manifest.get("semantic_rules_version") == "4.1":
        from recallpack.evidence_review_protocol import validate_execution_manifest_41

        validate_execution_manifest_41(
            manifest,
            artifact_bytes=artifact_bytes,
            repository_root=repository_root,
        )
        return
    if (
        manifest.get("semantic_rules_version") == "4.0"
        and manifest.get("descope_rung") != "Floor"
    ):
        _raise_validation_errors(
            [
                (
                    "legacy_non_floor_diagnostic_only",
                    "/descope_rung",
                    "legacy 4.0 non-Floor manifests require the diagnostic-only parser",
                )
            ]
        )
        return
    _validate_legacy_execution_manifest(
        manifest,
        definition="manifest",
        artifact_bytes=artifact_bytes,
        source_ledgers=source_ledgers,
    )


def validate_legacy_execution_manifest_diagnostic(
    manifest: Mapping[str, Any],
    *,
    artifact_bytes: Mapping[str, bytes],
    source_ledgers: Mapping[str, Mapping[str, Any]] | None = None,
) -> None:
    """Inspect historical 4.0 non-Floor records without claim registration."""

    if not (
        manifest.get("semantic_rules_version") == "4.0"
        and manifest.get("descope_rung") in {"Full", "R1", "R2"}
    ):
        _raise_validation_errors(
            [
                (
                    "legacy_diagnostic_manifest_required",
                    "/descope_rung",
                    "diagnostic parser accepts only historical 4.0 non-Floor manifests",
                )
            ]
        )
        return
    _validate_legacy_execution_manifest(
        manifest,
        definition="legacyManifest40",
        artifact_bytes=artifact_bytes,
        source_ledgers=source_ledgers,
    )


def _validate_legacy_execution_manifest(
    manifest: Mapping[str, Any],
    *,
    definition: str,
    artifact_bytes: Mapping[str, bytes],
    source_ledgers: Mapping[str, Mapping[str, Any]] | None,
) -> None:
    errors = _schema_errors(manifest, definition)
    if not isinstance(manifest, Mapping):
        _raise_validation_errors(errors)
        return

    input_catalog = manifest.get("input_artifact_catalog")
    evidence_scenarios = manifest.get("evidence_scenarios")
    execution_order = manifest.get("execution_order")
    if not isinstance(input_catalog, Mapping) or not isinstance(evidence_scenarios, list):
        _raise_validation_errors(errors)
        return

    scenario_index = {
        scenario.get("scenario_slot"): scenario
        for scenario in evidence_scenarios
        if isinstance(scenario, Mapping)
    }
    errors.extend(_validate_rung_grid(manifest, evidence_scenarios, execution_order))
    errors.extend(_validate_provider_settings(manifest))
    errors.extend(_validate_input_artifact_catalog(input_catalog, artifact_bytes))
    errors.extend(_validate_reference_artifacts(manifest, input_catalog, artifact_bytes))
    errors.extend(_validate_image_build_record(manifest, input_catalog, artifact_bytes))
    errors.extend(
        _validate_evidence_scenarios(
            manifest,
            scenario_index,
            input_catalog,
            artifact_bytes,
            source_ledgers or {},
        )
    )
    errors.extend(_validate_claim_declarations(manifest))
    _raise_validation_errors(errors)


def _validate_rung_grid(
    manifest: Mapping[str, Any],
    evidence_scenarios: list[Any],
    execution_order: Any,
) -> list[tuple[str, str, str]]:
    errors: list[tuple[str, str, str]] = []
    rung = manifest.get("descope_rung")
    scenario_slots = manifest.get("scenario_slots")
    variants = manifest.get("variants")
    if not isinstance(scenario_slots, list) or tuple(variants or ()) != _V4_VARIANTS:
        return errors

    scenario_counter = Counter()
    for index, scenario in enumerate(evidence_scenarios):
        if not isinstance(scenario, Mapping):
            continue
        scenario_counter[scenario.get("evidence_class")] += 1
        if scenario.get("scenario_slot") not in scenario_slots:
            errors.append(
                (
                    "invalid_rung_grid",
                    f"/evidence_scenarios/{index}/scenario_slot",
                    "scenario slot must appear in scenario_slots",
                )
            )

    expected_mix = {
        "Full": {"source_backed_synthetic": 3, "blind_holdout": 1},
        "R1": {"source_backed_synthetic": 2, "blind_holdout": 1},
        "R2": {"source_backed_synthetic": 2},
        "Floor": {"deterministic_diagnostic": 1},
    }.get(rung)
    if expected_mix is not None:
        actual_mix = {key: count for key, count in scenario_counter.items() if count}
        if actual_mix != expected_mix:
            errors.append(
                (
                    "invalid_rung_grid",
                    "/evidence_scenarios",
                    "evidence class mix must match the selected rung",
                )
            )

    if not isinstance(execution_order, list):
        return errors

    slot_ids: set[str] = set()
    slot_indexes: set[int] = set()
    composites: set[tuple[str, str, int]] = set()
    headline_counts: Counter[tuple[str, str]] = Counter()
    scenario_set = set(scenario_slots)
    variant_set = set(_V4_VARIANTS)
    for index, slot in enumerate(execution_order):
        if not isinstance(slot, Mapping):
            continue
        slot_id = slot.get("slot_id")
        slot_index = slot.get("slot_index")
        scenario_slot = slot.get("scenario_slot")
        variant_id = slot.get("variant_id")
        repetition = slot.get("repetition")
        designation = slot.get("planned_designation")
        if slot_id in slot_ids:
            errors.append(
                ("invalid_rung_grid", f"/execution_order/{index}/slot_id", "slot_id must be unique")
            )
        else:
            slot_ids.add(slot_id)
        if slot_index in slot_indexes:
            errors.append(
                (
                    "invalid_rung_grid",
                    f"/execution_order/{index}/slot_index",
                    "slot_index must be unique",
                )
            )
        else:
            slot_indexes.add(slot_index)
        composite = (scenario_slot, variant_id, repetition)
        if composite in composites:
            errors.append(
                (
                    "invalid_rung_grid",
                    f"/execution_order/{index}",
                    "scenario, variant, and repetition must be unique",
                )
            )
        else:
            composites.add(composite)
        if scenario_slot not in scenario_set or variant_id not in variant_set:
            errors.append(
                (
                    "invalid_rung_grid",
                    f"/execution_order/{index}",
                    "execution slot must reference declared scenario and variant",
                )
            )
        if designation == "headline":
            headline_counts[(scenario_slot, variant_id)] += 1
            if repetition not in (1, 2, 3):
                errors.append(
                    (
                        "invalid_rung_grid",
                        f"/execution_order/{index}/repetition",
                        "headline repetitions must be 1, 2, or 3",
                    )
                )
        if rung == "Floor" and designation != "diagnostic":
            errors.append(
                (
                    "invalid_rung_grid",
                    f"/execution_order/{index}/planned_designation",
                    "Floor execution slots must be diagnostic",
                )
            )

    if slot_indexes != set(range(len(execution_order))):
        errors.append(
            ("invalid_rung_grid", "/execution_order", "slot_index values must be contiguous from 0")
        )

    if rung == "Floor":
        if len(execution_order) != len(_V4_VARIANTS):
            errors.append(
                (
                    "invalid_rung_grid",
                    "/execution_order",
                    "Floor must declare one diagnostic slot per variant",
                )
            )
    else:
        for scenario_slot in scenario_slots:
            for variant_id in _V4_VARIANTS:
                if headline_counts[(scenario_slot, variant_id)] != 3:
                    errors.append(
                        (
                            "invalid_rung_grid",
                            "/execution_order",
                            "each scenario and variant must declare exactly three headline repetitions",
                        )
                    )
                    return errors
    return errors


def _validate_provider_settings(manifest: Mapping[str, Any]) -> list[tuple[str, str, str]]:
    errors: list[tuple[str, str, str]] = []
    rung = manifest.get("descope_rung")
    provider_settings = manifest.get("provider_settings")
    if not isinstance(provider_settings, Mapping):
        return errors

    mode = provider_settings.get("mode")
    family = provider_settings.get("provider_family")
    fallback = provider_settings.get("deterministic_fallback")
    models = provider_settings.get("models")
    if rung in {"Full", "R1", "R2"}:
        expected_models = {
            "memory_decision": "qwen3.7-plus-2026-05-26",
            "embedding": "text-embedding-v4",
            "rerank": "qwen3-rerank",
            "patch_generation": "qwen3.7-plus-2026-05-26",
        }
        if mode != "live" or family != "qwen_cloud" or fallback is not False:
            errors.append(
                (
                    "invalid_rung_grid",
                    "/provider_settings",
                    "headline rungs must use live qwen_cloud settings with no fallback",
                )
            )
        if models != expected_models:
            errors.append(
                (
                    "invalid_rung_grid",
                    "/provider_settings/models",
                    "headline rungs must pin the required provider model ids",
                )
            )
    elif rung == "Floor":
        if mode != "fake" or family != "deterministic_fake" or fallback is not True:
            errors.append(
                (
                    "invalid_rung_grid",
                    "/provider_settings",
                    "Floor must use deterministic diagnostic provider settings",
                )
            )
    return errors


def _validate_input_artifact_catalog(
    catalog: Mapping[str, Any],
    artifact_bytes: Mapping[str, bytes],
) -> list[tuple[str, str, str]]:
    errors: list[tuple[str, str, str]] = []
    seen_paths: set[str] = set()
    for artifact_id, record in catalog.items():
        pointer = f"/input_artifact_catalog/{artifact_id.replace('~', '~0').replace('/', '~1')}"
        if not isinstance(record, Mapping):
            continue
        kind = record.get("kind")
        relative_path = record.get("relative_path")
        if kind in _OUTPUT_ONLY_INPUT_KINDS:
            errors.append(
                (
                    "invalid_artifact_reference",
                    f"{pointer}/kind",
                    "input catalog must not contain output-only artifact kinds",
                )
            )
        if isinstance(relative_path, str):
            normalized = _normalize_relative_path(relative_path)
            if normalized != relative_path:
                errors.append(
                    (
                        "invalid_artifact_reference",
                        f"{pointer}/relative_path",
                        "relative_path must be normalized",
                    )
                )
            if normalized in seen_paths:
                errors.append(
                    (
                        "invalid_artifact_reference",
                        f"{pointer}/relative_path",
                        "relative_path must be unique",
                    )
                )
            else:
                seen_paths.add(normalized)
            errors.extend(_scan_text(relative_path, f"{pointer}/relative_path"))
        errors.extend(_validate_catalog_artifact(artifact_id, record, artifact_bytes, pointer))
    return errors


def _validate_reference_artifacts(
    manifest: Mapping[str, Any],
    catalog: Mapping[str, Any],
    artifact_bytes: Mapping[str, bytes],
) -> list[tuple[str, str, str]]:
    errors: list[tuple[str, str, str]] = []
    comparison = manifest.get("comparison_contract")
    evaluator = manifest.get("evaluator_contract")
    review = manifest.get("review")
    if isinstance(comparison, Mapping):
        reference_map = {
            "repository_snapshot_artifact_id": "repository_snapshot",
            "patch_provider_contract_artifact_id": "patch_provider_contract",
            "model_visible_snapshot_artifact_id": "model_visible_snapshot",
            "prompt_template_artifact_id": "prompt_template",
            "runner_contract_artifact_id": "runner_contract",
        }
        for field_name, expected_kind in reference_map.items():
            errors.extend(
                _resolve_artifact(
                    catalog,
                    artifact_bytes,
                    comparison.get(field_name),
                    expected_kind=expected_kind,
                    pointer=f"/comparison_contract/{field_name}",
                )[1]
            )
    if isinstance(evaluator, Mapping):
        reference_map = {
            "dockerfile_artifact_id": "dockerfile",
            "runner_artifact_id": "evaluator_runner",
            "build_record_artifact_id": "image_build_record",
        }
        for field_name, expected_kind in reference_map.items():
            errors.extend(
                _resolve_artifact(
                    catalog,
                    artifact_bytes,
                    evaluator.get(field_name),
                    expected_kind=expected_kind,
                    pointer=f"/evaluator_contract/{field_name}",
                )[1]
            )
        if evaluator.get("image_digest") != manifest.get("evaluator_image_digest"):
            errors.append(
                (
                    "invalid_artifact_reference",
                    "/evaluator_image_digest",
                    "top-level evaluator image digest must equal evaluator_contract.image_digest",
                )
            )
        if evaluator.get("image_digest") == evaluator.get("base_image_digest"):
            errors.append(
                (
                    "invalid_artifact_reference",
                    "/evaluator_contract/image_digest",
                    "image digest must differ from base image digest",
                )
            )
    if isinstance(review, Mapping):
        leakage_hashes = review.get("leakage_review_hashes")
        scenario_slots = manifest.get("scenario_slots")
        if isinstance(leakage_hashes, Mapping) and isinstance(scenario_slots, list):
            if set(leakage_hashes) != set(scenario_slots):
                errors.append(
                    (
                        "invalid_artifact_reference",
                        "/review/leakage_review_hashes",
                        "leakage review hashes must cover every scenario slot exactly once",
                    )
                )
    return errors


def _validate_image_build_record(
    manifest: Mapping[str, Any],
    catalog: Mapping[str, Any],
    artifact_bytes: Mapping[str, bytes],
) -> list[tuple[str, str, str]]:
    errors: list[tuple[str, str, str]] = []
    evaluator = manifest.get("evaluator_contract")
    if not isinstance(evaluator, Mapping):
        return errors

    build_record_artifact_id = evaluator.get("build_record_artifact_id")
    build_record, resolution_errors = _resolve_artifact(
        catalog,
        artifact_bytes,
        build_record_artifact_id,
        expected_kind="image_build_record",
        pointer="/evaluator_contract/build_record_artifact_id",
    )
    errors.extend(resolution_errors)
    if build_record is None:
        return errors

    parsed_build_record = _parse_json_payload(
        build_record["payload"],
        pointer="/evaluator_contract/build_record_artifact_id",
        code="invalid_artifact_reference",
        detail="image build record payload must be valid JSON",
        errors=errors,
    )
    if not isinstance(parsed_build_record, Mapping):
        return errors

    errors.extend(
        _schema_errors(
            parsed_build_record,
            "imageBuildRecord",
            default_code="invalid_artifact_reference",
        )
    )
    dockerfile, dockerfile_errors = _resolve_artifact(
        catalog,
        artifact_bytes,
        parsed_build_record.get("dockerfile_artifact_id"),
        expected_kind="dockerfile",
        pointer="/evaluator_contract/dockerfile_artifact_id",
    )
    runner, runner_errors = _resolve_artifact(
        catalog,
        artifact_bytes,
        parsed_build_record.get("runner_artifact_id"),
        expected_kind="evaluator_runner",
        pointer="/evaluator_contract/runner_artifact_id",
    )
    errors.extend(dockerfile_errors)
    errors.extend(runner_errors)
    if dockerfile is None or runner is None:
        return errors

    if parsed_build_record.get("build_context_root") != evaluator.get("build_context_root"):
        errors.append(
            (
                "invalid_artifact_reference",
                "/evaluator_contract/build_context_root",
                "build context root must match the evaluator contract",
            )
        )
    if parsed_build_record.get("platform") != evaluator.get("platform"):
        errors.append(
            (
                "invalid_artifact_reference",
                "/evaluator_contract/platform",
                "image build platform must match the evaluator contract",
            )
        )
    if parsed_build_record.get("dockerfile_sha256") != catalog[dockerfile["artifact_id"]]["sha256"]:
        errors.append(
            (
                "invalid_artifact_reference",
                "/evaluator_contract/dockerfile_artifact_id",
                "build record dockerfile hash must match the catalog",
            )
        )
    if parsed_build_record.get("runner_sha256") != catalog[runner["artifact_id"]]["sha256"]:
        errors.append(
            (
                "invalid_artifact_reference",
                "/evaluator_contract/runner_artifact_id",
                "build record runner hash must match the catalog",
            )
        )
    if (
        parsed_build_record.get("dockerfile_from_base_image_digest")
        != evaluator.get("base_image_digest")
    ):
        errors.append(
            (
                "invalid_artifact_reference",
                "/evaluator_contract/base_image_digest",
                "build record base image digest must match the evaluator contract",
            )
        )
    if parsed_build_record.get("output_image_digest") != evaluator.get("image_digest"):
        errors.append(
            (
                "invalid_artifact_reference",
                "/evaluator_contract/image_digest",
                "build record output image digest must match the evaluator contract",
            )
        )

    dockerfile_text = dockerfile["payload"].decode("utf-8", errors="strict")
    from_matches = _FROM_RE.findall(dockerfile_text)
    if len(from_matches) != 1 or "@sha256:" not in from_matches[0]:
        errors.append(
            (
                "invalid_artifact_reference",
                "/evaluator_contract/dockerfile_artifact_id",
                "Dockerfile must contain exactly one pinned FROM digest",
            )
        )
    else:
        parsed_digest = from_matches[0].split("@", 1)[1]
        if parsed_digest != evaluator.get("base_image_digest"):
            errors.append(
                (
                    "invalid_artifact_reference",
                    "/evaluator_contract/base_image_digest",
                    "Dockerfile FROM digest must match base_image_digest",
                )
            )
    return errors


def _validate_evidence_scenarios(
    manifest: Mapping[str, Any],
    scenario_index: Mapping[str, Mapping[str, Any]],
    catalog: Mapping[str, Any],
    artifact_bytes: Mapping[str, bytes],
    source_ledgers: Mapping[str, Mapping[str, Any]],
) -> list[tuple[str, str, str]]:
    errors: list[tuple[str, str, str]] = []
    label_hashes = manifest.get("label_hashes")
    review = manifest.get("review")
    reviewer_role = review.get("reviewer_role") if isinstance(review, Mapping) else None
    for index, scenario in enumerate(manifest.get("evidence_scenarios", [])):
        if not isinstance(scenario, Mapping):
            continue
        pointer = f"/evidence_scenarios/{index}"
        slot = scenario.get("scenario_slot")
        evidence_class = scenario.get("evidence_class")
        custody_state = scenario.get("custody_state")
        if evidence_class == "source_backed_synthetic":
            if reviewer_role != "external-reviewer":
                errors.append(
                    (
                        "invalid_custody_state",
                        "/review/reviewer_role",
                        "source-backed headline scenarios require an external reviewer",
                    )
                )
            if custody_state not in {"externally_reviewed", "revealed_for_scoring"}:
                errors.append(
                    (
                        "invalid_custody_state",
                        f"{pointer}/custody_state",
                        "source-backed synthetic scenarios require external custody",
                    )
                )
            if not isinstance(scenario.get("provenance"), Mapping):
                errors.append(
                    (
                        "invalid_custody_state",
                        f"{pointer}/provenance",
                        "source-backed synthetic scenarios require provenance",
                    )
                )
            ledger, ledger_errors = _resolve_source_ledger(
                scenario,
                catalog,
                artifact_bytes,
                source_ledgers,
                pointer,
            )
            errors.extend(ledger_errors)
            if ledger is not None:
                if ledger.get("scenario_slot") != slot:
                    errors.append(
                        (
                            "invalid_artifact_reference",
                            f"{pointer}/source_ledger_artifact_id",
                            "source ledger scenario_slot must match the evidence scenario",
                        )
                    )
                refs = [entry.get("source_ref") for entry in ledger.get("entries", [])]
                if len(refs) != len(set(refs)):
                    errors.append(
                        (
                            "invalid_artifact_reference",
                            f"{pointer}/source_ledger_artifact_id",
                            "source ledger source_ref values must be unique",
                        )
                    )
        elif evidence_class == "blind_holdout":
            if custody_state not in {"sealed_external", "revealed_for_scoring"}:
                errors.append(
                    (
                        "invalid_custody_state",
                        f"{pointer}/custody_state",
                        "blind holdout scenarios require external custody",
                    )
                )
            if scenario.get("provenance") is not None:
                errors.append(
                    (
                        "invalid_custody_state",
                        f"{pointer}/provenance",
                        "blind holdout scenarios must not expose public provenance",
                    )
                )
            errors.extend(
                _resolve_artifact(
                    catalog,
                    artifact_bytes,
                    scenario.get("source_ledger_artifact_id"),
                    expected_kind="source_ledger_hash",
                    pointer=f"{pointer}/source_ledger_artifact_id",
                )[1]
            )
        elif evidence_class == "deterministic_diagnostic":
            if custody_state != "workspace_diagnostic":
                errors.append(
                    (
                        "invalid_custody_state",
                        f"{pointer}/custody_state",
                        "deterministic diagnostic scenarios must stay in workspace_diagnostic custody",
                    )
                )
            if scenario.get("provenance") is not None:
                errors.append(
                    (
                        "invalid_custody_state",
                        f"{pointer}/provenance",
                        "deterministic diagnostic scenarios must not declare provenance",
                    )
                )
            _, ledger_errors = _resolve_source_ledger(
                scenario,
                catalog,
                artifact_bytes,
                source_ledgers,
                pointer,
            )
            errors.extend(ledger_errors)
        else:
            errors.append(
                (
                    "invalid_rung_grid",
                    f"{pointer}/evidence_class",
                    "unsupported evidence_class for execution manifest slice A",
                )
            )

        errors.extend(
            _resolve_artifact(
                catalog,
                artifact_bytes,
                scenario.get("leakage_review_artifact_id"),
                expected_kind="leakage_review",
                pointer=f"{pointer}/leakage_review_artifact_id",
            )[1]
        )
        errors.extend(
            _resolve_artifact(
                catalog,
                artifact_bytes,
                scenario.get("fixture_artifact_id"),
                expected_kind="fixture",
                pointer=f"{pointer}/fixture_artifact_id",
            )[1]
        )
        label_hash_payload, label_hash_errors = _resolve_artifact(
            catalog,
            artifact_bytes,
            scenario.get("label_hash_artifact_id"),
            expected_kind="label_hash",
            pointer=f"{pointer}/label_hash_artifact_id",
        )
        errors.extend(label_hash_errors)
        errors.extend(
            _resolve_artifact(
                catalog,
                artifact_bytes,
                scenario.get("hidden_test_hash_artifact_id"),
                expected_kind="hidden_test_hash",
                pointer=f"{pointer}/hidden_test_hash_artifact_id",
            )[1]
        )
        expected_label_hash = scenario.get("relation_label_ledger_sha256")
        if not isinstance(label_hashes, Mapping) or label_hashes.get(slot) != expected_label_hash:
            errors.append(
                (
                    "invalid_artifact_reference",
                    f"{pointer}/relation_label_ledger_sha256",
                    "manifest.label_hashes[scenario_slot] must equal relation_label_ledger_sha256",
                )
            )
        payload_bytes = label_hash_payload.get("payload") if isinstance(label_hash_payload, Mapping) else None
        try:
            label_hash_text = bytes(payload_bytes).decode("utf-8", errors="strict")
        except (TypeError, UnicodeDecodeError):
            label_hash_text = None
        if label_hash_text != expected_label_hash:
            errors.append(
                (
                    "invalid_artifact_reference",
                    f"{pointer}/label_hash_artifact_id",
                    "label_hash_artifact_id payload must equal the frozen relation_label_ledger_sha256",
                )
            )

    if set(scenario_index) != set(manifest.get("scenario_slots", [])):
        errors.append(
            (
                "invalid_rung_grid",
                "/evidence_scenarios",
                "evidence_scenarios must cover every declared scenario slot exactly once",
            )
        )
    return errors


def _validate_claim_declarations(manifest: Mapping[str, Any]) -> list[tuple[str, str, str]]:
    errors: list[tuple[str, str, str]] = []
    claim_declarations = manifest.get("claim_declarations")
    if not isinstance(claim_declarations, list):
        return errors

    claim_ids: set[str] = set()
    claim_types: set[str] = set()
    for index, declaration in enumerate(claim_declarations):
        if not isinstance(declaration, Mapping):
            continue
        claim_id = declaration.get("claim_id")
        claim_type = declaration.get("claim_type")
        if claim_id in claim_ids:
            errors.append(
                (
                    "invalid_claim_reference",
                    f"/claim_declarations/{index}/claim_id",
                    "claim_id must be unique",
                )
            )
        else:
            claim_ids.add(claim_id)
        if claim_type in claim_types:
            errors.append(
                (
                    "invalid_claim_reference",
                    f"/claim_declarations/{index}/claim_type",
                    "claim_type must not be declared more than once",
                )
            )
        else:
            claim_types.add(claim_type)

    expected_types = {
        "Full": {"structural_runtime", "downstream_superiority", "false_supersession_rate"},
        "R1": {"structural_runtime"},
        "R2": {"structural_runtime"},
        "Floor": {"structural_runtime"},
    }.get(manifest.get("descope_rung"))
    if expected_types is not None and claim_types != expected_types:
        errors.append(
            (
                "invalid_claim_reference",
                "/claim_declarations",
                "claim types must match the selected rung exactly",
            )
        )
    if manifest.get("descope_rung") == "Floor" and len(claim_declarations) == 1:
        declaration = claim_declarations[0]
        canonical_floor_fields = {
            "claim_type": "structural_runtime",
            "activation_rule_id": "structural_runtime_gate",
            "eligible_rungs": ["Full", "R1", "R2", "Floor"],
            "statement": (
                "The frozen runtime and evaluator contract executed deterministically."
            ),
            "rerunnable_command": (
                "PYTHONPATH=src .venv/bin/python3 -m unittest "
                "tests.test_hero_evaluation"
            ),
            "limitations": [
                "Floor is diagnostic-only.",
                "No live or superiority claim is allowed.",
            ],
        }
        if not isinstance(declaration, Mapping) or any(
            declaration.get(field) != value
            for field, value in canonical_floor_fields.items()
        ):
            errors.append(
                (
                    "invalid_claim_reference",
                    "/claim_declarations/0",
                    "Floor must use evaluator-owned canonical structural claim fields",
                )
            )
    return errors


def _resolve_source_ledger(
    scenario: Mapping[str, Any],
    catalog: Mapping[str, Any],
    artifact_bytes: Mapping[str, bytes],
    source_ledgers: Mapping[str, Mapping[str, Any]],
    pointer: str,
) -> tuple[dict[str, Any] | None, list[tuple[str, str, str]]]:
    resolved, errors = _resolve_artifact(
        catalog,
        artifact_bytes,
        scenario.get("source_ledger_artifact_id"),
        expected_kind="source_ledger",
        pointer=f"{pointer}/source_ledger_artifact_id",
    )
    if resolved is None:
        return None, errors

    scenario_slot = scenario.get("scenario_slot")
    provided_ledger = source_ledgers.get(scenario_slot)
    ledger_from_artifact = _parse_json_payload(
        resolved["payload"],
        pointer=f"{pointer}/source_ledger_artifact_id",
        code="invalid_artifact_reference",
        detail="source ledger payload must be valid JSON",
        errors=errors,
    )
    if ledger_from_artifact is None:
        return None, errors

    ledger = dict(provided_ledger) if isinstance(provided_ledger, Mapping) else ledger_from_artifact
    errors.extend(
        _schema_errors(
            ledger,
            "sourceLedger",
            default_code="invalid_artifact_reference",
        )
    )
    if canonical_json(ledger).encode("utf-8") != resolved["payload"]:
        errors.append(
            (
                "invalid_artifact_reference",
                f"{pointer}/source_ledger_artifact_id",
                "source ledger payload must match the frozen artifact bytes",
            )
        )
    return ledger, errors
