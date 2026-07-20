from __future__ import annotations

import re
from typing import Any, Mapping

from recallpack.budget import canonical_json
from recallpack.evidence_common import _schema_errors, _sha256_hex
from recallpack.evidence_run_support import _scenario_record
from recallpack.review_json import review_json_sha256


def _scan_model_visible_artifact(
    artifact_id: Any,
    record: Mapping[str, Any] | None,
    artifact_bytes: Mapping[str, bytes],
    pointer: str,
    forbidden_tokens: set[str],
    allowed_source_refs: set[str],
) -> list[tuple[str, str, str]]:
    errors: list[tuple[str, str, str]] = []
    if not isinstance(artifact_id, str):
        errors.append(
            (
                "invalid_relation_evidence",
                pointer,
                "model-visible artifact ids must be present for relation-leakage validation",
            )
        )
        return errors
    payload = artifact_bytes.get(artifact_id)
    if not isinstance(payload, (bytes, bytearray)):
        errors.append(
            (
                "invalid_relation_evidence",
                pointer,
                "model-visible artifact bytes must exist for relation-leakage validation",
            )
        )
        return errors
    payload_bytes = bytes(payload)
    if not isinstance(record, Mapping):
        errors.append(
            (
                "invalid_relation_evidence",
                pointer,
                "model-visible artifacts must resolve to frozen manifest catalog records",
            )
        )
        return errors
    if record.get("bytes") != len(payload_bytes) or record.get("sha256") != _sha256_hex(payload_bytes):
        errors.append(
            (
                "invalid_relation_evidence",
                pointer,
                "model-visible artifact bytes must match the frozen manifest catalog",
            )
        )
        return errors
    try:
        text = payload_bytes.decode("utf-8", errors="strict")
    except UnicodeDecodeError:
        errors.append(
            (
                "invalid_relation_evidence",
                pointer,
                "model-visible artifacts must be valid UTF-8 for relation-leakage validation",
            )
        )
        return errors
    scan_text = text
    for source_ref in sorted(allowed_source_refs, key=len, reverse=True):
        standalone_ref = re.compile(
            rf"(?<![A-Za-z0-9._:-]){re.escape(source_ref)}(?![A-Za-z0-9._:-])"
        )
        scan_text = standalone_ref.sub("", scan_text)
    for token in forbidden_tokens:
        if token and token in scan_text:
            errors.append(
                (
                    "invalid_relation_evidence",
                    pointer,
                    "relation evidence must stay out of model-visible artifacts",
                )
            )
            break
    return errors


def _validate_relation_opportunities(
    run: Mapping[str, Any],
    manifest: Mapping[str, Any],
    source_ledger: Mapping[str, Any],
    artifact_bytes: Mapping[str, bytes],
    output_catalog: Mapping[str, Any],
    relation_label_ledger: Mapping[str, Any] | None,
) -> list[tuple[str, str, str]]:
    errors: list[tuple[str, str, str]] = []
    relation_opportunities = run.get("relation_opportunities")
    variant_id = run.get("variant_id")
    designation = run.get("designation")
    if not isinstance(relation_opportunities, list):
        return errors

    if variant_id != "recallpack" or designation != "headline":
        if relation_opportunities:
            errors.append(
                (
                    "invalid_relation_evidence",
                    "/relation_opportunities",
                    "only RecallPack headline runs may carry relation_opportunities",
                )
            )
        return errors

    if not isinstance(relation_label_ledger, Mapping):
        errors.append(
            (
                "invalid_relation_evidence",
                "/relation_opportunities",
                "RecallPack headline runs must be validated against a relation_label_ledger",
            )
        )
        return errors

    errors.extend(
        _schema_errors(
            relation_label_ledger,
            "relationLabelLedger",
            default_code="invalid_relation_evidence",
        )
    )
    scenario = _scenario_record(manifest, run.get("scenario_id"))
    if scenario is None:
        return errors

    rules_version = manifest.get("semantic_rules_version")
    ledger_bytes = canonical_json(relation_label_ledger).encode("utf-8")
    if rules_version == "4.1":
        expected_ledger_hash = manifest.get("label_hashes", {}).get(run.get("scenario_id"))
        actual_ledger_hash = review_json_sha256(relation_label_ledger)
    else:
        expected_ledger_hash = scenario.get("relation_label_ledger_sha256")
        actual_ledger_hash = _sha256_hex(ledger_bytes)
    if expected_ledger_hash != actual_ledger_hash:
        errors.append(
            (
                "invalid_relation_evidence",
                "/relation_opportunities",
                "relation_label_ledger must match the frozen scenario ledger hash",
            )
        )
    if relation_label_ledger.get("scenario_slot") != run.get("scenario_id"):
        errors.append(
            (
                "invalid_relation_evidence",
                "/relation_opportunities",
                "relation_label_ledger scenario_slot must match run.scenario_id",
            )
        )

    source_ledger_bytes = canonical_json(source_ledger).encode("utf-8")
    source_ledger_hash = (
        review_json_sha256(source_ledger)
        if rules_version == "4.1"
        else _sha256_hex(source_ledger_bytes)
    )
    if relation_label_ledger.get("source_ledger_sha256") != source_ledger_hash:
        errors.append(
            (
                "invalid_relation_evidence",
                "/relation_opportunities",
                "relation_label_ledger must bind the frozen scenario source ledger hash",
            )
        )
    source_entries = source_ledger.get("entries")
    if not isinstance(source_entries, list):
        return errors
    available_refs: set[str] = {
        entry.get("source_ref")
        for entry in source_entries
        if isinstance(entry, Mapping) and isinstance(entry.get("source_ref"), str)
    }

    entries = relation_label_ledger.get("entries")
    if not isinstance(entries, list):
        return errors
    ledger_by_id: dict[str, Mapping[str, Any]] = {}
    for index, entry in enumerate(entries):
        if not isinstance(entry, Mapping):
            continue
        opportunity_id = entry.get("opportunity_id")
        if isinstance(opportunity_id, str):
            if opportunity_id in ledger_by_id:
                errors.append(
                    (
                        "invalid_relation_evidence",
                        f"/relation_opportunities/{index}/opportunity_id",
                        "relation_label_ledger opportunity_id values must be unique",
                    )
                )
            else:
                ledger_by_id[opportunity_id] = entry
        prior_source_ref = entry.get("prior_source_ref")
        candidate_source_ref = entry.get("candidate_source_ref")
        if (
            isinstance(prior_source_ref, str)
            and prior_source_ref == candidate_source_ref
        ):
            errors.append(
                (
                    "invalid_relation_evidence",
                    f"/relation_opportunities/{index}/candidate_source_ref",
                    "relation_label_ledger entries must bind distinct prior and candidate refs",
                )
            )
        for field_name in ("prior_source_ref", "candidate_source_ref"):
            if entry.get(field_name) not in available_refs:
                errors.append(
                    (
                        "invalid_relation_evidence",
                        f"/relation_opportunities/{index}/{field_name}",
                        "relation_label_ledger endpoint refs must resolve in the frozen source ledger",
                    )
                )

    run_ids: set[str] = set()
    for index, opportunity in enumerate(relation_opportunities):
        if not isinstance(opportunity, Mapping):
            continue
        opportunity_id = opportunity.get("opportunity_id")
        if not isinstance(opportunity_id, str):
            continue
        if opportunity_id in run_ids:
            errors.append(
                (
                    "invalid_relation_evidence",
                    f"/relation_opportunities/{index}/opportunity_id",
                    "relation_opportunities opportunity_id values must be unique per run",
                )
            )
            continue
        run_ids.add(opportunity_id)
        ledger_entry = ledger_by_id.get(opportunity_id)
        if ledger_entry is None:
            errors.append(
                (
                    "invalid_relation_evidence",
                    f"/relation_opportunities/{index}/opportunity_id",
                    "every relation_opportunity must resolve to the frozen relation_label_ledger",
                )
            )
            continue
        for field_name in ("prior_source_ref", "candidate_source_ref", "relation_kind"):
            if opportunity.get(field_name) != ledger_entry.get(field_name):
                errors.append(
                    (
                        "invalid_relation_evidence",
                        f"/relation_opportunities/{index}/{field_name}",
                        "relation_opportunities must match the exact frozen ledger endpoints and labels",
                    )
                )

    if run_ids != set(ledger_by_id):
        errors.append(
            (
                "invalid_relation_evidence",
                "/relation_opportunities",
                "RecallPack headline runs must reproduce the exact frozen relation_label_ledger entry set",
            )
        )

    forbidden_tokens = {
        canonical_json(relation_label_ledger),
        "relation_label_ledger",
        "opportunity_id",
        "relation_kind",
        "prior_source_ref",
        "candidate_source_ref",
    }
    for entry in entries:
        if not isinstance(entry, Mapping):
            continue
        for field_name in (
            "opportunity_id",
            "relation_kind",
        ):
            value = entry.get(field_name)
            if isinstance(value, str):
                forbidden_tokens.add(value)

    input_catalog = manifest.get("input_artifact_catalog")
    comparison_contract = manifest.get("comparison_contract")
    if isinstance(input_catalog, Mapping) and isinstance(comparison_contract, Mapping):
        if rules_version == "4.1":
            manifest_artifacts = (
                (
                    scenario.get("model_visible_snapshot_artifact_id"),
                    "model_visible_snapshot",
                    "/evidence_scenarios/model_visible_snapshot_artifact_id",
                ),
                (
                    comparison_contract.get("prompt_template_artifact_id"),
                    "prompt_template",
                    "/comparison_contract/prompt_template_artifact_id",
                ),
            )
        else:
            manifest_artifacts = tuple(
                (
                    comparison_contract.get(field_name),
                    expected_kind,
                    f"/comparison_contract/{field_name}",
                )
                for field_name, expected_kind in (
                    ("model_visible_snapshot_artifact_id", "model_visible_snapshot"),
                    ("prompt_template_artifact_id", "prompt_template"),
                )
            )
        for artifact_id, expected_kind, pointer in manifest_artifacts:
            record = input_catalog.get(artifact_id) if isinstance(artifact_id, str) else None
            if not isinstance(record, Mapping) or record.get("kind") != expected_kind:
                errors.append(
                    (
                        "invalid_relation_evidence",
                        pointer,
                        f"artifact must resolve to kind {expected_kind}",
                    )
                )
                continue
            errors.extend(
                _scan_model_visible_artifact(
                    artifact_id,
                    record,
                    artifact_bytes,
                    f"/input_artifact_catalog/{artifact_id.replace('~', '~0').replace('/', '~1')}",
                    forbidden_tokens,
                    available_refs,
                )
            )

    for artifact_id, record in output_catalog.items():
        if not isinstance(record, Mapping) or record.get("kind") != "model_visible_context":
            continue
        errors.extend(
            _scan_model_visible_artifact(
                artifact_id,
                record,
                artifact_bytes,
                f"/run_output_artifact_catalog/{artifact_id.replace('~', '~0').replace('/', '~1')}",
                forbidden_tokens,
                available_refs,
            )
        )
    return errors


def _validate_run_outcome(run: Mapping[str, Any]) -> list[tuple[str, str, str]]:
    errors: list[tuple[str, str, str]] = []
    outcome = run.get("outcome")
    if not isinstance(outcome, Mapping):
        return errors

    designation = run.get("designation")
    if designation == "invalidated_technical":
        errors.extend(
            _expect_outcome(
                outcome,
                ("invalidated", "sandbox", "technical_failure"),
            )
        )
        if run.get("test_result") is not None:
            errors.append(
                (
                    "invalid_run_outcome",
                    "/test_result",
                    "technical invalidation must not carry a completed test result",
                )
            )
        patch = run.get("patch")
        if not isinstance(patch, Mapping) or patch.get("accepted") is not True:
            errors.append(
                (
                    "invalid_run_outcome",
                    "/patch",
                    "sandbox technical invalidation requires its accepted patch",
                )
            )
        return errors
    if designation == "invalidated_abort":
        errors.extend(
            _expect_outcome(
                outcome,
                ("invalidated", "aborted", "manual_abort"),
            )
        )
        if run.get("test_result") is not None:
            errors.append(
                (
                    "invalid_run_outcome",
                    "/test_result",
                    "manual abort must not carry a completed test result",
                )
            )
        return errors

    patch = run.get("patch")
    test_result = run.get("test_result")
    if isinstance(test_result, Mapping):
        expected_outcome = (
            ("completed", "complete", "success")
            if test_result.get("full_suite_passed") is True
            else ("adverse", "hidden_test", "hidden_tests_failed")
        )
        if not isinstance(patch, Mapping) or patch.get("accepted") is not True:
            errors.append(
                (
                    "invalid_run_outcome",
                    "/patch",
                    "executed suites require an accepted patch artifact",
                )
            )
        errors.extend(_expect_outcome(outcome, expected_outcome))
        return errors

    if isinstance(patch, Mapping):
        if patch.get("accepted") is False:
            errors.extend(
                _expect_outcome(
                    outcome,
                    ("adverse", "patch_generation", "patch_rejected"),
                )
            )
        elif patch.get("accepted") is True:
            errors.append(
                (
                    "invalid_run_outcome",
                    "/test_result",
                    "accepted patch runs without invalidation must carry a test_result",
                )
            )
        return errors

    errors.extend(_expect_outcome(outcome, ("adverse", "patch_generation", "empty_patch")))
    return errors


def _expect_outcome(
    outcome: Mapping[str, Any],
    expected: tuple[str, str, str],
) -> list[tuple[str, str, str]]:
    errors: list[tuple[str, str, str]] = []
    actual = (
        outcome.get("status"),
        outcome.get("stage"),
        outcome.get("code"),
    )
    for field_name, actual_value, expected_value in zip(
        ("status", "stage", "code"),
        actual,
        expected,
    ):
        if actual_value != expected_value:
            errors.append(
                (
                    "invalid_run_outcome",
                    f"/outcome/{field_name}",
                    "run outcome must match the closed patch/test truth table",
                )
            )
    return errors
