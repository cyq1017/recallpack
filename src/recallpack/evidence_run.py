from __future__ import annotations

from typing import Any, Mapping

from recallpack.budget import canonical_json
from recallpack.evidence_common import (
    _raise_validation_errors,
    _resolve_artifact,
    _schema_errors,
    _sha256_hex,
)
from recallpack.evidence_run_relations import (
    _validate_relation_opportunities,
    _validate_run_outcome,
)
from recallpack.evidence_run_support import (
    _resolve_output_artifact,
    _scenario_record,
    _validate_artifact_hashes,
    _validate_patch,
    _validate_test_result,
)
from recallpack.tokenization import TokenizerUnavailableError, default_tokenizer
from recallpack.review_json import execution_manifest_sha256
from recallpack.evidence_custody import validate_descendant_binding
from recallpack.evidence_execution_manifest import validate_execution_manifest
from recallpack.evidence_review_protocol import (
    ManifestRegistry,
    _fail,
    validate_registered_execution_manifest_41,
)


def validate_evaluation_run(
    run: Mapping[str, Any],
    manifest: Mapping[str, Any],
    *,
    artifact_bytes: Mapping[str, bytes],
    source_ledger: Mapping[str, Any],
    relation_label_ledger: Mapping[str, Any] | None = None,
    manifest_registry: ManifestRegistry | None = None,
) -> None:
    rules_version = manifest.get("semantic_rules_version")
    if rules_version == "4.1":
        if manifest_registry is None:
            _fail(
                "invalid_manifest_binding",
                "/execution_manifest_sha256",
                "4.1 run validation requires the manifest registry",
            )
        validate_registered_execution_manifest_41(
            manifest,
            artifact_bytes=artifact_bytes,
            registry=manifest_registry,
        )
        validate_descendant_binding(run, manifest, manifest_registry)
    elif rules_version == "4.0" and manifest.get("descope_rung") != "Floor":
        _fail(
            "legacy_non_floor_diagnostic_only",
            "/descope_rung",
            "legacy 4.0 non-Floor runs require the diagnostic-only validator",
        )
    else:
        validate_execution_manifest(
            manifest,
            artifact_bytes=artifact_bytes,
            source_ledgers={str(source_ledger.get("scenario_slot")): source_ledger},
        )
    _validate_evaluation_run_semantics(
        run,
        manifest,
        artifact_bytes=artifact_bytes,
        source_ledger=source_ledger,
        relation_label_ledger=relation_label_ledger,
    )


def validate_legacy_evaluation_run_diagnostic(
    run: Mapping[str, Any],
    manifest: Mapping[str, Any],
    *,
    artifact_bytes: Mapping[str, bytes],
    source_ledger: Mapping[str, Any],
    relation_label_ledger: Mapping[str, Any] | None = None,
) -> None:
    """Exercise historical 4.0 run semantics without admitting evidence."""

    if not (
        manifest.get("semantic_rules_version") == "4.0"
        and manifest.get("descope_rung") in {"Full", "R1", "R2"}
    ):
        _fail(
            "legacy_diagnostic_manifest_required",
            "/descope_rung",
            "diagnostic run validator accepts only historical 4.0 non-Floor manifests",
        )
    _validate_evaluation_run_semantics(
        run,
        manifest,
        artifact_bytes=artifact_bytes,
        source_ledger=source_ledger,
        relation_label_ledger=relation_label_ledger,
    )


def _validate_evaluation_run_semantics(
    run: Mapping[str, Any],
    manifest: Mapping[str, Any],
    *,
    artifact_bytes: Mapping[str, bytes],
    source_ledger: Mapping[str, Any],
    relation_label_ledger: Mapping[str, Any] | None,
) -> None:
    errors = _schema_errors(run, "run")
    if not isinstance(run, Mapping):
        _raise_validation_errors(errors)
        return

    output_catalog = run.get("run_output_artifact_catalog")
    provider_traces = run.get("provider_traces")
    variant_id = run.get("variant_id")
    if not isinstance(output_catalog, Mapping) or not isinstance(provider_traces, list):
        _raise_validation_errors(errors)
        return

    errors.extend(_validate_run_manifest_binding(run, manifest))
    errors.extend(_validate_slot_and_designation(run, manifest))
    errors.extend(_validate_output_catalog(output_catalog, artifact_bytes))
    errors.extend(
        _validate_context_evidence(
            run,
            manifest,
            output_catalog,
            artifact_bytes,
            variant_id,
        )
    )
    errors.extend(_validate_metrics(run))
    errors.extend(_validate_selected_sources(run, manifest, source_ledger, artifact_bytes))
    errors.extend(
        _validate_relation_opportunities(
            run,
            manifest,
            source_ledger,
            artifact_bytes,
            output_catalog,
            relation_label_ledger,
        )
    )
    errors.extend(
        _validate_provider_traces(
            run,
            manifest,
            provider_traces,
            variant_id,
        )
    )
    errors.extend(
        _validate_patch(
            run,
            manifest,
            output_catalog,
            artifact_bytes,
            _resolve_output_artifact,
        )
    )
    errors.extend(
        _validate_test_result(
            run,
            manifest,
            output_catalog,
            artifact_bytes,
            _resolve_output_artifact,
        )
    )
    errors.extend(_validate_run_outcome(run))
    errors.extend(_validate_artifact_hashes(run, output_catalog))
    _raise_validation_errors(errors)


def _validate_run_manifest_binding(
    run: Mapping[str, Any],
    manifest: Mapping[str, Any],
) -> list[tuple[str, str, str]]:
    errors: list[tuple[str, str, str]] = []
    if run.get("manifest_version") != manifest.get("manifest_version"):
        errors.append(
            (
                "invalid_run_reference",
                "/manifest_version",
                "run manifest_version must equal the execution manifest version",
            )
        )
    if run.get("semantic_rules_version") != manifest.get("semantic_rules_version"):
        errors.append(
            (
                "invalid_run_reference",
                "/semantic_rules_version",
                "run semantic rules must equal the execution manifest",
            )
        )
    if run.get("execution_manifest_sha256") != execution_manifest_sha256(manifest):
        errors.append(
            (
                "invalid_run_reference",
                "/execution_manifest_sha256",
                "run execution_manifest_sha256 must equal the canonical manifest hash",
            )
        )
    return errors


def _validate_slot_and_designation(
    run: Mapping[str, Any],
    manifest: Mapping[str, Any],
) -> list[tuple[str, str, str]]:
    errors: list[tuple[str, str, str]] = []
    execution_order = manifest.get("execution_order")
    slot_index = run.get("slot_index")
    if not isinstance(execution_order, list) or not isinstance(slot_index, int):
        return errors
    if slot_index < 0 or slot_index >= len(execution_order):
        errors.append(
            (
                "invalid_run_reference",
                "/slot_index",
                "slot_index must resolve to a predeclared execution slot",
            )
        )
        return errors

    slot = execution_order[slot_index]
    if not isinstance(slot, Mapping):
        return errors
    attempt_no = run.get("attempt_no")
    repetition = slot.get("repetition")
    if isinstance(attempt_no, int) and isinstance(repetition, int) and attempt_no < repetition:
        errors.append(
            (
                "invalid_replacement",
                "/attempt_no",
                "attempt_no must be at least the predeclared slot repetition",
            )
        )
    comparisons = (
        ("scenario_id", "scenario_slot"),
        ("variant_id", "variant_id"),
    )
    for run_field, slot_field in comparisons:
        if run.get(run_field) != slot.get(slot_field):
            errors.append(
                (
                    "invalid_run_reference",
                    f"/{run_field}",
                    f"run {run_field} must match the predeclared execution slot",
                )
            )

    planned_designation = slot.get("planned_designation")
    designation = run.get("designation")
    if planned_designation == "headline" and designation == "diagnostic":
        errors.append(
            (
                "invalid_designation",
                "/designation",
                "diagnostic runs must bind only to diagnostic slots",
            )
        )
    if planned_designation == "diagnostic" and designation == "headline":
        errors.append(
            (
                "invalid_designation",
                "/designation",
                "headline runs must bind only to headline slots",
            )
        )

    failure = run.get("failure")
    technical_codes = manifest.get("technical_failure_codes")
    if designation == "invalidated_technical":
        if not isinstance(failure, Mapping) or failure.get("code") not in technical_codes:
            errors.append(
                (
                    "invalid_failure_code",
                    "/failure/code",
                    "invalidated_technical runs must use a manifest technical failure code",
                )
            )
    elif designation == "invalidated_abort":
        if not isinstance(failure, Mapping) or failure.get("code") != "manual_abort":
            errors.append(
                (
                    "invalid_failure_code",
                    "/failure/code",
                    "invalidated_abort runs must use the manual_abort failure code",
                )
            )
    elif failure is not None:
        errors.append(
            (
                "invalid_designation",
                "/failure",
                "headline and diagnostic runs must not carry a failure payload",
            )
        )
    return errors


def _validate_output_catalog(
    output_catalog: Mapping[str, Any],
    artifact_bytes: Mapping[str, bytes],
) -> list[tuple[str, str, str]]:
    errors: list[tuple[str, str, str]] = []
    for artifact_id, record in output_catalog.items():
        if not isinstance(record, Mapping):
            continue
        errors.extend(
            _resolve_output_artifact(
                output_catalog,
                artifact_bytes,
                artifact_id,
                expected_kind=record.get("kind"),
                pointer=f"/run_output_artifact_catalog/{artifact_id.replace('~', '~0').replace('/', '~1')}",
            )[1]
        )
    return errors


def _validate_context_evidence(
    run: Mapping[str, Any],
    manifest: Mapping[str, Any],
    output_catalog: Mapping[str, Any],
    artifact_bytes: Mapping[str, bytes],
    variant_id: Any,
) -> list[tuple[str, str, str]]:
    errors: list[tuple[str, str, str]] = []
    context_evidence = run.get("context_evidence")
    comparison_contract = manifest.get("comparison_contract")
    if not isinstance(context_evidence, Mapping) or not isinstance(comparison_contract, Mapping):
        return errors

    resolved, resolution_errors = _resolve_output_artifact(
        output_catalog,
        artifact_bytes,
        context_evidence.get("artifact_id"),
        expected_kind="model_visible_context",
        pointer="/context_evidence/artifact_id",
    )
    errors.extend(resolution_errors)
    if resolved is None:
        return errors

    catalog_record = resolved["record"]
    payload = resolved["payload"]
    if catalog_record.get("sha256") != context_evidence.get("sha256"):
        errors.append(
            (
                "invalid_context_evidence",
                "/context_evidence/sha256",
                "context_evidence sha256 must equal the embedded artifact hash",
            )
        )
    tokenizer_spec = comparison_contract.get("tokenizer")
    if context_evidence.get("tokenizer") != tokenizer_spec:
        errors.append(
            (
                "invalid_context_evidence",
                "/context_evidence/tokenizer",
                "context_evidence tokenizer must equal the comparison contract tokenizer",
            )
        )

    try:
        context_text = payload.decode("utf-8", errors="strict")
        exact_token_count = default_tokenizer().count(context_text)
    except (UnicodeDecodeError, TokenizerUnavailableError, TypeError):
        errors.append(
            (
                "invalid_context_evidence",
                "/context_evidence/exact_token_count",
                "context evidence must be UTF-8 and exact-token-countable",
            )
        )
        return errors

    if context_evidence.get("exact_token_count") != exact_token_count:
        errors.append(
            (
                "invalid_context_evidence",
                "/context_evidence/exact_token_count",
                "context_evidence exact_token_count must equal the recomputed token count",
            )
        )

    budget_policy = context_evidence.get("budget_policy")
    if variant_id == "raw_full_history":
        if budget_policy != "unbounded_reference":
            errors.append(
                (
                    "invalid_context_evidence",
                    "/context_evidence/budget_policy",
                    "raw_full_history runs must use unbounded_reference budget policy",
                )
            )
    else:
        if budget_policy != "exact_512_max":
            errors.append(
                (
                    "invalid_context_evidence",
                    "/context_evidence/budget_policy",
                    "budget-comparable runs must use exact_512_max budget policy",
                )
            )
        budget_tokens = comparison_contract.get("budget_tokens")
        if isinstance(budget_tokens, int) and exact_token_count > budget_tokens:
            errors.append(
                (
                    "invalid_context_evidence",
                    "/context_evidence/exact_token_count",
                    "context evidence token count must not exceed the comparison budget",
                )
            )
    return errors


def _validate_metrics(run: Mapping[str, Any]) -> list[tuple[str, str, str]]:
    errors: list[tuple[str, str, str]] = []
    metrics = run.get("metrics")
    latency_ms = run.get("latency_ms")
    usage = run.get("usage")
    selected_sources = run.get("selected_sources")
    if not isinstance(metrics, Mapping):
        return errors

    selected_total = metrics.get("selected_total")
    if isinstance(selected_sources, list) and selected_total != len(selected_sources):
        errors.append(
            (
                "invalid_run_arithmetic",
                "/metrics/selected_total",
                "selected_total must equal len(selected_sources)",
            )
        )
    checks = (
        ("stale_selected", "selected_total"),
        ("required_selected", "required_total"),
        ("candidate_prior_selected", "candidate_prior_total"),
    )
    for numerator_key, denominator_key in checks:
        numerator = metrics.get(numerator_key)
        denominator = metrics.get(denominator_key)
        if isinstance(numerator, int) and isinstance(denominator, int) and numerator > denominator:
            errors.append(
                (
                    "invalid_run_arithmetic",
                    f"/metrics/{numerator_key}",
                    f"{numerator_key} must not exceed {denominator_key}",
                )
            )
    if (
        isinstance(metrics.get("required_selected"), int)
        and isinstance(selected_total, int)
        and metrics["required_selected"] > selected_total
    ):
        errors.append(
            (
                "invalid_run_arithmetic",
                "/metrics/required_selected",
                "required_selected must not exceed selected_total",
            )
        )
    if (
        isinstance(metrics.get("stale_selected"), int)
        and isinstance(selected_total, int)
        and metrics["stale_selected"] > selected_total
    ):
        errors.append(
            (
                "invalid_run_arithmetic",
                "/metrics/stale_selected",
                "stale_selected must not exceed selected_total",
            )
        )

    if isinstance(latency_ms, Mapping) and isinstance(latency_ms.get("stages"), Mapping):
        stage_total = sum(
            value for value in latency_ms["stages"].values() if isinstance(value, int)
        )
        if isinstance(latency_ms.get("total"), int) and latency_ms["total"] < stage_total:
            errors.append(
                (
                    "invalid_run_arithmetic",
                    "/latency_ms/total",
                    "latency_ms.total must be at least the sum of latency_ms.stages",
                )
            )
    if isinstance(usage, Mapping):
        total = usage.get("total_tokens")
        input_tokens = usage.get("input_tokens")
        output_tokens = usage.get("output_tokens")
        if (
            isinstance(total, int)
            and isinstance(input_tokens, int)
            and isinstance(output_tokens, int)
            and total != input_tokens + output_tokens
        ):
            errors.append(
                (
                    "invalid_run_arithmetic",
                    "/usage/total_tokens",
                    "usage.total_tokens must equal usage.input_tokens plus usage.output_tokens",
                )
            )
    return errors


def _validate_selected_sources(
    run: Mapping[str, Any],
    manifest: Mapping[str, Any],
    source_ledger: Mapping[str, Any],
    artifact_bytes: Mapping[str, bytes],
) -> list[tuple[str, str, str]]:
    errors: list[tuple[str, str, str]] = []
    scenario = _scenario_record(manifest, run.get("scenario_id"))
    if scenario is None:
        errors.append(
            (
                "invalid_run_reference",
                "/scenario_id",
                "scenario_id must resolve to a manifest evidence_scenario",
            )
        )
        return errors

    errors.extend(
        _schema_errors(
            source_ledger,
            "sourceLedger",
            default_code="invalid_run_reference",
        )
    )
    if source_ledger.get("scenario_slot") != run.get("scenario_id"):
        errors.append(
            (
                "invalid_run_reference",
                "/selected_sources",
                "source_ledger scenario_slot must match run.scenario_id",
            )
        )
    entries = source_ledger.get("entries")
    if isinstance(entries, list):
        refs = [entry.get("source_ref") for entry in entries if isinstance(entry, Mapping)]
        if len(refs) != len(set(refs)):
            errors.append(
                (
                    "invalid_run_reference",
                    "/selected_sources",
                    "source_ledger source_ref values must be unique",
                )
            )

    artifact_id = scenario.get("source_ledger_artifact_id")
    catalog = manifest.get("input_artifact_catalog")
    if not isinstance(catalog, Mapping):
        return errors
    record = catalog.get(artifact_id)
    if not isinstance(record, Mapping):
        errors.append(
            (
                "invalid_run_reference",
                "/selected_sources",
                "scenario source ledger artifact must resolve from the manifest input catalog",
            )
        )
        return errors

    ledger_bytes = canonical_json(source_ledger).encode("utf-8")
    if record.get("kind") == "source_ledger":
        resolved, resolution_errors = _resolve_artifact(
            catalog,
            artifact_bytes,
            artifact_id,
            expected_kind="source_ledger",
            pointer="/selected_sources",
        )
        errors.extend(resolution_errors)
        if resolved is None:
            return errors
        payload = resolved["payload"]
        if ledger_bytes != bytes(payload):
            errors.append(
                (
                    "invalid_run_reference",
                    "/selected_sources",
                    "source_ledger must match the frozen source_ledger artifact bytes",
                )
            )
    elif record.get("kind") == "source_ledger_hash":
        resolved, resolution_errors = _resolve_artifact(
            catalog,
            artifact_bytes,
            artifact_id,
            expected_kind="source_ledger_hash",
            pointer="/selected_sources",
        )
        errors.extend(resolution_errors)
        if resolved is None:
            return errors
        payload = resolved["payload"]
        if _sha256_hex(ledger_bytes) != bytes(payload).decode("utf-8", errors="replace").strip():
            errors.append(
                (
                    "invalid_run_reference",
                    "/selected_sources",
                    "source_ledger must match the frozen source_ledger_hash artifact",
                )
            )
    else:
        errors.append(
            (
                "invalid_run_reference",
                "/selected_sources",
                "scenario source ledger artifact must be source_ledger or source_ledger_hash",
            )
        )

    selected_sources = run.get("selected_sources")
    if isinstance(selected_sources, list) and isinstance(entries, list):
        available_refs = {
            entry.get("source_ref")
            for entry in entries
            if isinstance(entry, Mapping)
        }
        for index, source_ref in enumerate(selected_sources):
            if source_ref not in available_refs:
                errors.append(
                    (
                        "invalid_run_reference",
                        f"/selected_sources/{index}",
                        "selected_sources entries must resolve to the scenario source ledger",
                    )
                )
    return errors


def _validate_provider_traces(
    run: Mapping[str, Any],
    manifest: Mapping[str, Any],
    provider_traces: list[Any],
    variant_id: Any,
) -> list[tuple[str, str, str]]:
    errors: list[tuple[str, str, str]] = []
    comparison_contract = manifest.get("comparison_contract")
    provider_settings = manifest.get("provider_settings")
    usage = run.get("usage")
    if (
        not isinstance(comparison_contract, Mapping)
        or not isinstance(provider_settings, Mapping)
        or not isinstance(usage, Mapping)
        or not isinstance(variant_id, str)
    ):
        return errors

    role_contracts = comparison_contract.get("variant_provider_role_contract")
    if not isinstance(role_contracts, Mapping):
        return errors
    role_contract = role_contracts.get(variant_id)
    if not isinstance(role_contract, Mapping):
        return errors

    required_roles = list(role_contract.get("required_roles", []))
    allowed_roles = set(role_contract.get("allowed_roles", []))
    repeatable_roles = set(role_contract.get("repeatable_roles", []))
    singleton_roles = set(role_contract.get("singleton_roles", []))

    counts: dict[str, int] = {}
    input_sum = 0
    output_sum = 0
    total_sum = 0
    for index, trace in enumerate(provider_traces):
        if not isinstance(trace, Mapping):
            continue
        role = trace.get("role")
        counts[role] = counts.get(role, 0) + 1
        if role not in allowed_roles:
            errors.append(
                (
                    "invalid_provider_trace",
                    f"/provider_traces/{index}/role",
                    "provider trace role must be allowed for the variant",
                )
            )
        expected_model = provider_settings.get("models", {}).get(role)
        if trace.get("provider_family") != provider_settings.get("provider_family"):
            errors.append(
                (
                    "invalid_provider_trace",
                    f"/provider_traces/{index}/provider_family",
                    "provider_family must match the execution manifest",
                )
            )
        if trace.get("model_name") != expected_model:
            errors.append(
                (
                    "invalid_provider_trace",
                    f"/provider_traces/{index}/model_name",
                    "provider trace model_name must match the execution manifest",
                )
            )
        if trace.get("live") != (provider_settings.get("mode") == "live"):
            errors.append(
                (
                    "invalid_provider_trace",
                    f"/provider_traces/{index}/live",
                    "provider trace live flag must match the execution manifest",
                )
            )
        if trace.get("deterministic_fallback") != provider_settings.get("deterministic_fallback"):
            errors.append(
                (
                    "invalid_provider_trace",
                    f"/provider_traces/{index}/deterministic_fallback",
                    "provider trace fallback flag must match the execution manifest",
                )
            )
        if provider_settings.get("mode") == "live" and trace.get("request_id_present") is not True:
            errors.append(
                (
                    "invalid_provider_trace",
                    f"/provider_traces/{index}/request_id_present",
                    "live provider traces must record request_id presence",
                )
            )
        token_usage = trace.get("token_usage")
        if isinstance(token_usage, Mapping):
            trace_input = token_usage.get("input_tokens")
            trace_output = token_usage.get("output_tokens")
            trace_total = token_usage.get("total_tokens")
            if (
                provider_settings.get("mode") == "live"
                and token_usage.get("reported_by_provider") is not True
            ):
                errors.append(
                    (
                        "invalid_provider_trace",
                        f"/provider_traces/{index}/token_usage/reported_by_provider",
                        "live provider traces must use provider-reported token usage",
                    )
                )
            if (
                isinstance(trace_input, int)
                and isinstance(trace_output, int)
                and isinstance(trace_total, int)
            ):
                if trace_total != trace_input + trace_output:
                    errors.append(
                        (
                            "invalid_provider_trace",
                            f"/provider_traces/{index}/token_usage/total_tokens",
                            "provider trace total_tokens must equal input plus output tokens",
                        )
                    )
                input_sum += trace_input
                output_sum += trace_output
                total_sum += trace_total

    if set(counts) != set(required_roles):
        errors.append(
            (
                "invalid_provider_trace",
                "/provider_traces",
                "provider trace role set must equal the required roles for the variant",
            )
        )
    for role in required_roles:
        if counts.get(role, 0) < 1:
            errors.append(
                (
                    "invalid_provider_trace",
                    "/provider_traces",
                    f"required provider role {role} must appear at least once",
                )
            )
        if role in singleton_roles and counts.get(role, 0) != 1:
            errors.append(
                (
                    "invalid_provider_trace",
                    "/provider_traces",
                    f"singleton provider role {role} must appear exactly once",
                )
            )
        if role not in repeatable_roles and role not in singleton_roles and counts.get(role, 0) != 1:
            errors.append(
                (
                    "invalid_provider_trace",
                    "/provider_traces",
                    f"non-repeatable provider role {role} must appear exactly once",
                )
            )
    for role, count in counts.items():
        if role in singleton_roles and count != 1:
            errors.append(
                (
                    "invalid_provider_trace",
                    "/provider_traces",
                    f"singleton provider role {role} must appear exactly once",
                )
            )
        if role not in repeatable_roles and role not in singleton_roles and count != 1:
            errors.append(
                (
                    "invalid_provider_trace",
                    "/provider_traces",
                    f"non-repeatable provider role {role} must appear exactly once",
                )
            )

    if usage.get("provider_calls") != len(provider_traces):
        errors.append(
            (
                "invalid_run_arithmetic",
                "/usage/provider_calls",
                "usage.provider_calls must equal len(provider_traces)",
            )
        )
    if usage.get("input_tokens") != input_sum:
        errors.append(
            (
                "invalid_run_arithmetic",
                "/usage/input_tokens",
                "usage.input_tokens must equal the provider trace input token sum",
            )
        )
    if usage.get("output_tokens") != output_sum:
        errors.append(
            (
                "invalid_run_arithmetic",
                "/usage/output_tokens",
                "usage.output_tokens must equal the provider trace output token sum",
            )
        )
    if usage.get("total_tokens") != total_sum:
        errors.append(
            (
                "invalid_run_arithmetic",
                "/usage/total_tokens",
                "usage.total_tokens must equal the provider trace total token sum",
            )
        )
    return errors
