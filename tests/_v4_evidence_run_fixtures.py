from __future__ import annotations

import copy
import difflib
from typing import Any

from recallpack.evidence_pipeline import (
    build_test_only_finalized_runner_output_authority,
)
from recallpack.tokenization import default_tokenizer
from tests._v4_evidence_common import (
    DEFAULT_CONTEXT_TEXT,
    EXECUTION_MANIFEST_SHA256,
    V4_VARIANTS,
    artifact,
    canonical_json_bytes,
    canonical_sha256,
    sha,
    sha256_hex_bytes,
)
from tests._v4_evidence_manifest_fixtures import (
    build_execution_input_artifact_bytes,
    build_source_ledgers,
)


def build_provider_trace(
    role: str,
    *,
    provider_family: str = "qwen_cloud",
    model_name: str = "qwen3.7-plus-2026-05-26",
    live: bool = True,
    deterministic_fallback: bool = False,
    token_usage: tuple[int, int, int] = (5, 3, 8),
) -> dict[str, object]:
    return {
        "role": role,
        "provider_family": provider_family,
        "model_name": model_name,
        "request_purpose": f"{role}_purpose",
        "input_item_count": 1,
        "input_token_estimate": 1,
        "output_item_count": 1,
        "live": live,
        "deterministic_fallback": deterministic_fallback,
        "request_id_present": True,
        "token_usage": {
            "input_tokens": token_usage[0],
            "output_tokens": token_usage[1],
            "total_tokens": token_usage[2],
            "reported_by_provider": True,
        },
    }


def build_run_output_artifact_bytes(
    *,
    context_text: str = DEFAULT_CONTEXT_TEXT,
) -> dict[str, bytes]:
    original = "def retry():\n    return False\n"
    patched = "def retry():\n    return True\n"
    patch_diff = "".join(
        difflib.unified_diff(
            original.splitlines(keepends=True),
            patched.splitlines(keepends=True),
            fromfile="a/src/retry.py",
            tofile="b/src/retry.py",
        )
    )
    return {
        "trace_runtime": b'{"runtime":"trace"}',
        "context_visible": context_text.encode("utf-8"),
        "patch_diff": patch_diff.encode("utf-8"),
        "original_file_retry": original.encode("utf-8"),
        "patched_file_retry": patched.encode("utf-8"),
        "stdout_text": b"stdout placeholder",
        "stderr_text": b"stderr placeholder",
        "test_result_json": (
            b'{"tests":[{"name":"test_runtime_contract","status":"passed"}]}'
        ),
    }


def build_run_output_artifact_catalog(
    *,
    context_text: str = DEFAULT_CONTEXT_TEXT,
    run_id: str = "eval_A1",
) -> dict[str, object]:
    payloads = build_run_output_artifact_bytes(context_text=context_text)
    return {
        "trace_runtime": artifact("runtime_trace", "runs/trace.json", payloads["trace_runtime"]),
        "context_visible": artifact(
            "model_visible_context",
            "runs/context.txt",
            payloads["context_visible"],
        ),
        "patch_diff": artifact("patch_diff", "runs/patch.diff", payloads["patch_diff"]),
        "original_file_retry": artifact(
            "original_file",
            "runs/shared/original-files/src/retry.py",
            payloads["original_file_retry"],
        ),
        "patched_file_retry": artifact(
            "patched_file",
            "runs/shared/patched-files/src/retry.py",
            payloads["patched_file_retry"],
        ),
        "stdout_text": artifact("stdout", "runs/stdout.txt", payloads["stdout_text"]),
        "stderr_text": artifact("stderr", "runs/stderr.txt", payloads["stderr_text"]),
        "test_result_json": artifact(
            "test_result",
            "runs/test-result.json",
            payloads["test_result_json"],
        ),
    }


def build_relation_opportunity(
    *,
    opportunity_id: str = "opp_1",
    scenario_id: str = "projectodyssey",
    relation_kind: str = "hard_negative",
    decision: str = "keep_independent",
    outcome: str = "correct",
    prior_source_ref: str | None = None,
    candidate_source_ref: str | None = None,
) -> dict[str, object]:
    return {
        "opportunity_id": opportunity_id,
        "relation_kind": relation_kind,
        "prior_source_ref": prior_source_ref or f"{scenario_id}:turn-001",
        "candidate_source_ref": candidate_source_ref or f"{scenario_id}:turn-002",
        "decision": decision,
        "outcome": outcome,
        "model_visible": False,
    }


def build_aggregate_artifact_hashes(
    manifest: dict[str, object],
    run_records: list[dict[str, object]],
) -> dict[str, str]:
    hashes = {"execution_manifest": canonical_sha256(manifest)}
    for run_record in run_records:
        hashes[f"run:{run_record['run_id']}"] = canonical_sha256(run_record)
    return hashes


def _slot_index_for(
    manifest: dict[str, object],
    *,
    scenario_id: str,
    variant_id: str,
    repetition: int,
) -> int:
    for slot in manifest["execution_order"]:
        if (
            slot["scenario_slot"] == scenario_id
            and slot["variant_id"] == variant_id
            and slot["repetition"] == repetition
        ):
            return slot["slot_index"]
    return 0


def _claim_type_for_id(manifest: dict[str, object], claim_id: str) -> str:
    for declaration in manifest["claim_declarations"]:
        if declaration["claim_id"] == claim_id:
            return declaration["claim_type"]
    return "structural_runtime"


def build_aggregate_scope(
    run_records: list[dict[str, object]],
    *,
    designation: str = "headline",
    scenario_ids: list[str] | None = None,
    variant_ids: list[str] | None = None,
) -> dict[str, object]:
    records = run_records or []
    return {
        "selection_rule": "all_accepted_runs_in_scope",
        "designation": designation,
        "scenario_ids": scenario_ids
        or sorted({run_record["scenario_id"] for run_record in records}),
        "variant_ids": variant_ids
        or sorted({run_record["variant_id"] for run_record in records}),
    }


def build_evaluation_run(
    manifest: dict[str, object],
    *,
    run_id: str = "eval_A1",
    scenario_id: str = "projectodyssey",
    variant_id: str = "semantic_rerank",
    slot_index: int | None = None,
    attempt_no: int = 1,
    designation: str = "headline",
    full_suite_passed: bool = True,
    exact_token_count: int | None = None,
    budget_policy: str = "exact_512_max",
    execution_manifest_sha256: str | None = None,
    provider_roles: list[str] | None = None,
    provider_family: str | None = None,
    live: bool | None = None,
    deterministic_fallback: bool | None = None,
    output_catalog: dict[str, object] | None = None,
    relation_opportunities: list[dict[str, object]] | None = None,
    failure: dict[str, object] | None = None,
) -> dict[str, object]:
    if slot_index is None:
        slot_index = _slot_index_for(
            manifest,
            scenario_id=scenario_id,
            variant_id=variant_id,
            repetition=attempt_no,
        )
    if variant_id == "raw_full_history":
        budget_policy = "unbounded_reference"
    role_contract = manifest["comparison_contract"]["variant_provider_role_contract"][
        variant_id
    ]
    provider_roles = provider_roles or list(role_contract["required_roles"])
    provider_family = provider_family or manifest["provider_settings"]["provider_family"]
    live = manifest["provider_settings"]["mode"] == "live" if live is None else live
    deterministic_fallback = (
        manifest["provider_settings"]["deterministic_fallback"]
        if deterministic_fallback is None
        else deterministic_fallback
    )
    output_catalog = copy.deepcopy(
        output_catalog or build_run_output_artifact_catalog(run_id=run_id)
    )
    if exact_token_count is None:
        exact_token_count = default_tokenizer().count(DEFAULT_CONTEXT_TEXT)
    passed = 1 if full_suite_passed else 0
    failed = 0 if full_suite_passed else 1
    stage = "complete" if full_suite_passed else "hidden_test"
    code = "success" if full_suite_passed else "hidden_tests_failed"
    status = "completed" if full_suite_passed else "adverse"
    if designation == "invalidated_technical":
        status = "invalidated"
        stage = "sandbox"
        code = "technical_failure"
        failure = failure or {
            "code": "sandbox_timeout",
            "detail": "simulated technical failure",
            "evidence_sha256": sha("9"),
        }
    elif designation == "invalidated_abort":
        status = "invalidated"
        stage = "aborted"
        code = "manual_abort"
        failure = failure or {
            "code": "manual_abort",
            "detail": "simulated abort",
            "evidence_sha256": sha("a"),
        }
    test_result = {
        "full_suite_passed": full_suite_passed,
        "passed": passed,
        "failed": failed,
        "exit_code": 0 if full_suite_passed else 1,
        "timed_out": False,
        "sandbox": {
            "platform": manifest["evaluator_contract"]["platform"],
            "image_digest": manifest["evaluator_contract"]["image_digest"],
            "base_image_digest": manifest["evaluator_contract"]["base_image_digest"],
            "uid": 65532,
            "gid": 65532,
            "cpus": 1,
            "memory_bytes": 1073741824,
            "pids": 128,
            "network_none": True,
            "read_only_root": True,
            "drop_all_capabilities": True,
            "no_new_privileges": True,
            "tmp_is_tmpfs": True,
            "tmpfs_size_bytes": 67108864,
            "repository_mount_mode": "rw",
            "hidden_test_mount_mode": "ro",
            "repository_root_canonical": True,
            "hidden_test_root_canonical": True,
            "roots_distinct": True,
            "wall_timeout_seconds": 120,
        },
        "test_result_artifact_id": "test_result_json",
        "stdout_artifact_id": "stdout_text",
        "stderr_artifact_id": "stderr_text",
        "tests": [
            {
                "name": "test_runtime_contract",
                "status": "passed" if full_suite_passed else "failed",
                "duration_ms": 1,
                "evidence_artifact_id": "stdout_text",
            }
        ],
    }
    if designation in {"invalidated_technical", "invalidated_abort"}:
        test_result = None
        output_catalog.pop("test_result_json")
    manifest_sha = execution_manifest_sha256 or canonical_sha256(manifest)
    return {
        "record_type": "evaluation_run",
        "run_id": run_id,
        "manifest_version": manifest["manifest_version"],
        "semantic_rules_version": manifest["semantic_rules_version"],
        "execution_manifest_sha256": manifest_sha,
        "scenario_id": scenario_id,
        "variant_id": variant_id,
        "slot_index": slot_index,
        "attempt_no": attempt_no,
        "designation": designation,
        "outcome": {"status": status, "stage": stage, "code": code},
        "context_evidence": {
            "artifact_id": "context_visible",
            "sha256": output_catalog["context_visible"]["sha256"],
            "exact_token_count": exact_token_count,
            "tokenizer": {
                "encoding": "o200k_base",
                "package": "tiktoken",
                "package_version": "0.13.0",
                "exact": True,
            },
            "budget_policy": budget_policy,
        },
        "selected_sources": [f"{scenario_id}:turn-001"],
        "metrics": {
            "stale_selected": 0,
            "selected_total": 1,
            "required_selected": 1,
            "required_total": 1,
            "candidate_prior_selected": 1,
            "candidate_prior_total": 1,
        },
        "relation_opportunities": copy.deepcopy(relation_opportunities or []),
        "patch": {
            "accepted": True,
            "diff_artifact_id": "patch_diff",
            "diff_sha256": output_catalog["patch_diff"]["sha256"],
            "validation_status": "accepted",
            "original_files": [
                {
                    "path": "src/retry.py",
                    "sha256": output_catalog["original_file_retry"]["sha256"],
                    "bytes": output_catalog["original_file_retry"]["bytes"],
                }
            ],
            "files": [
                {
                    "path": "src/retry.py",
                    "sha256": output_catalog["patched_file_retry"]["sha256"],
                    "bytes": output_catalog["patched_file_retry"]["bytes"],
                }
            ],
        },
        "test_result": test_result,
        "usage": {
            "provider_calls": len(provider_roles),
            "input_tokens": 5 * len(provider_roles),
            "output_tokens": 3 * len(provider_roles),
            "total_tokens": 8 * len(provider_roles),
        },
        "latency_ms": {"total": 10, "stages": {"retrieval": 2, "sandbox": 3}},
        "provider_traces": [
            build_provider_trace(
                role,
                provider_family=provider_family,
                model_name=manifest["provider_settings"]["models"][role],
                live=live,
                deterministic_fallback=deterministic_fallback,
            )
            for role in provider_roles
        ],
        "run_output_artifact_catalog": output_catalog,
        "artifact_hashes": {
            artifact_id: artifact_record["sha256"]
            for artifact_id, artifact_record in output_catalog.items()
        },
        "failure": failure,
    }


def build_aggregate_report(
    manifest: dict[str, object],
    *,
    aggregate_id: str = "agg_A1",
    claim_id: str = "claim_structural_runtime",
    claim_type: str | None = None,
    run_records: list[dict[str, object]] | None = None,
    run_ids: list[str] | None = None,
    adverse_run_ids: list[str] | None = None,
    metrics: list[dict[str, object]] | None = None,
    scope: dict[str, object] | None = None,
    numerator: int = 1,
    denominator: int = 1,
    n: int = 1,
    rate: float | None = 1.0,
    execution_manifest_sha256: str | None = None,
) -> dict[str, object]:
    if run_records is None and run_ids is not None:
        raise ValueError("run_records are required when overriding run_ids")
    run_records = copy.deepcopy(run_records or [build_evaluation_run(manifest)])
    if run_ids is None:
        run_ids = [run_record["run_id"] for run_record in run_records]
    if adverse_run_ids is None:
        adverse_run_ids = [
            run_record["run_id"]
            for run_record in run_records
            if run_record["outcome"]["status"] == "adverse"
        ]
    if metrics is None:
        metrics = [
            {
                "metric_id": "runtime_contract_success",
                "n": n,
                "numerator": numerator,
                "denominator": denominator,
                "rate": rate,
            }
        ]
    return {
        "record_type": "aggregate_report",
        "aggregate_id": aggregate_id,
        "manifest_version": manifest["manifest_version"],
        "semantic_rules_version": manifest["semantic_rules_version"],
        "execution_manifest_sha256": execution_manifest_sha256 or canonical_sha256(
            manifest
        ),
        "claim_id": claim_id,
        "claim_type": claim_type or _claim_type_for_id(manifest, claim_id),
        "scope": scope or build_aggregate_scope(run_records),
        "run_ids": run_ids,
        "adverse_run_ids": adverse_run_ids,
        "metrics": metrics,
        "limitations": ["Diagnostic aggregate only."],
        "artifact_hashes": build_aggregate_artifact_hashes(manifest, run_records),
    }


def build_evidence_manifest(
    manifest: dict[str, object],
    *,
    run_records: list[dict[str, object]] | None = None,
    aggregate_records: list[dict[str, object]] | None = None,
    status: str = "final",
    previous_evidence_manifest_sha256: str | None = None,
) -> dict[str, object]:
    run_records = run_records or [build_evaluation_run(manifest)]
    if aggregate_records is None:
        aggregate_records = [build_aggregate_report(manifest, run_records=run_records)]
    output_catalog = copy.deepcopy(run_records[0]["run_output_artifact_catalog"])
    for run_record in run_records:
        output_catalog[f"run_{run_record['run_id']}"] = artifact(
            "evaluation_run",
            f"runs/{run_record['run_id']}.json",
            canonical_json_bytes(run_record),
        )
    for aggregate_record in aggregate_records:
        output_catalog[aggregate_record["aggregate_id"]] = artifact(
            "aggregate_report",
            f"aggregates/{aggregate_record['aggregate_id']}.json",
            canonical_json_bytes(aggregate_record),
        )
    claims: list[dict[str, object]] = []
    for declaration in manifest["claim_declarations"]:
        if status == "partial":
            claims.append(
                {
                    "claim_id": declaration["claim_id"],
                    "claim_type": declaration["claim_type"],
                    "activation_rule_id": declaration["activation_rule_id"],
                    "status": "disabled",
                    "decision_reason": "evidence_incomplete",
                    "statement": declaration["statement"],
                    "evidence_artifact_ids": [],
                    "rerunnable_command": declaration["rerunnable_command"],
                    "limitations": list(declaration["limitations"]),
                }
            )
            continue
        claim_status = "enabled"
        decision_reason = "threshold_passed"
        if declaration["claim_type"] != "structural_runtime":
            claim_status = "disabled"
            decision_reason = "threshold_failed"
        claims.append(
            {
                "claim_id": declaration["claim_id"],
                "claim_type": declaration["claim_type"],
                "activation_rule_id": declaration["activation_rule_id"],
                "status": claim_status,
                "decision_reason": decision_reason,
                "statement": declaration["statement"],
                "evidence_artifact_ids": [
                    f"run_{run_records[0]['run_id']}",
                    aggregate_records[0]["aggregate_id"],
                ],
                "rerunnable_command": declaration["rerunnable_command"],
                "limitations": list(declaration["limitations"]),
            }
        )
    return {
        "record_type": "evidence_manifest",
        "evidence_manifest_id": "evidence_A1",
        "evidence_manifest_version": "v4",
        "created_at": "2026-07-12T00:00:00Z",
        "semantic_rules_version": "4.0",
        "execution_manifest_version": manifest["manifest_version"],
        "execution_manifest_sha256": canonical_sha256(manifest),
        "previous_evidence_manifest_sha256": previous_evidence_manifest_sha256,
        "status": status,
        "output_artifact_catalog": output_catalog,
        "run_ids": [run_record["run_id"] for run_record in run_records],
        "aggregate_ids": [
            aggregate_record["aggregate_id"] for aggregate_record in aggregate_records
        ],
        "claims": claims,
    }


def build_artifact_bytes(
    manifest: dict[str, object],
    *,
    source_ledgers: dict[str, dict[str, object]] | None = None,
    simulated_external_holdout: dict[str, object] | None = None,
    run_records: list[dict[str, object]] | None = None,
    aggregate_records: list[dict[str, object]] | None = None,
    evidence_manifest: dict[str, object] | None = None,
    model_visible_snapshot_text: str = "",
    prompt_template_text: str = "",
    context_text: str = DEFAULT_CONTEXT_TEXT,
    leakage_review_text: str = "",
) -> dict[str, bytes]:
    if not model_visible_snapshot_text:
        from tests._v4_evidence_common import DEFAULT_MODEL_VISIBLE_SNAPSHOT_TEXT

        model_visible_snapshot_text = DEFAULT_MODEL_VISIBLE_SNAPSHOT_TEXT
    if not prompt_template_text:
        from tests._v4_evidence_common import DEFAULT_PROMPT_TEMPLATE_TEXT

        prompt_template_text = DEFAULT_PROMPT_TEMPLATE_TEXT
    if not leakage_review_text:
        from tests._v4_evidence_common import DEFAULT_LEAKAGE_REVIEW_TEXT

        leakage_review_text = DEFAULT_LEAKAGE_REVIEW_TEXT
    artifact_bytes = build_execution_input_artifact_bytes(
        manifest,
        source_ledgers=source_ledgers or build_source_ledgers(),
        simulated_external_holdout=simulated_external_holdout,
        model_visible_snapshot_text=model_visible_snapshot_text,
        prompt_template_text=prompt_template_text,
        leakage_review_text=leakage_review_text,
    )
    run_records = run_records or []
    run_output_bytes = build_run_output_artifact_bytes(context_text=context_text)
    for run_record in run_records:
        for artifact_id, payload in run_output_bytes.items():
            artifact_bytes[artifact_id] = payload
        artifact_bytes[f"run_{run_record['run_id']}"] = canonical_json_bytes(run_record)
    aggregate_records = aggregate_records or []
    for aggregate_record in aggregate_records:
        artifact_bytes[aggregate_record["aggregate_id"]] = canonical_json_bytes(
            aggregate_record
        )
    if evidence_manifest is not None:
        artifact_bytes[evidence_manifest["evidence_manifest_id"]] = canonical_json_bytes(
            evidence_manifest
        )
    return artifact_bytes


def build_attempt_summary(
    run_id: str,
    variant_id: str,
    *,
    full_suite_passed: bool,
    designation: str = "headline",
    execution_manifest_sha256: str = EXECUTION_MANIFEST_SHA256,
    failure_code: str | None = None,
) -> dict[str, object]:
    if designation == "invalidated_technical":
        outcome = {
            "status": "invalidated",
            "stage": "sandbox",
            "code": "technical_failure",
        }
    elif designation == "invalidated_abort":
        outcome = {
            "status": "invalidated",
            "stage": "aborted",
            "code": "manual_abort",
        }
    else:
        outcome = {
            "status": "completed" if full_suite_passed else "adverse",
            "stage": "complete" if full_suite_passed else "hidden_test",
            "code": "success" if full_suite_passed else "hidden_tests_failed",
        }
    return {
        "run_id": run_id,
        "execution_manifest_sha256": execution_manifest_sha256,
        "scenario_id": "diag-project-a",
        "variant_id": variant_id,
        "designation": designation,
        "outcome": outcome,
        "test_result": {"full_suite_passed": full_suite_passed},
        "failure": None
        if failure_code is None
        else {"code": failure_code, "detail": "simulated", "evidence_sha256": sha("1")},
    }


def build_floor_runner_payloads(
    manifest: dict[str, object],
) -> dict[str, dict[str, object]]:
    payloads: dict[str, dict[str, object]] = {}
    for index, variant_id in enumerate(V4_VARIANTS):
        full_suite_passed = index % 2 == 0
        context_text = (
            f"goal=diagnostic handoff\nvariant={variant_id}\n"
            "source=diag-project-a:turn-001\n"
        )
        context_payload = context_text.encode("utf-8")
        original_file_payload = "def retry():\n    return None\n"
        patched_file_payload = (
            f"def diagnostic_{index}():\n    return {full_suite_passed!r}\n"
        )
        patch_payload = "".join(
            difflib.unified_diff(
                original_file_payload.splitlines(keepends=True),
                patched_file_payload.splitlines(keepends=True),
                fromfile="a/src/retry.py",
                tofile="b/src/retry.py",
                lineterm="\n",
            )
        ).encode("utf-8")
        role_contract = manifest["comparison_contract"][
            "variant_provider_role_contract"
        ][variant_id]
        roles = list(role_contract["required_roles"])
        provider_traces = [
            build_provider_trace(
                role,
                provider_family="deterministic_fake",
                model_name=manifest["provider_settings"]["models"][role],
                live=False,
                deterministic_fallback=True,
            )
            for role in roles
        ]
        test_status = "passed" if full_suite_passed else "failed"
        payloads[variant_id] = {
            "run_id": f"eval_Floor{index}",
            "variant_id": variant_id,
            "full_suite_passed": full_suite_passed,
            "stdout": f"{variant_id} stdout",
            "stderr": f"{variant_id} stderr",
            "context_text": context_text,
            "context_sha256": sha256_hex_bytes(context_payload),
            "context_bytes": len(context_payload),
            "exact_token_count": default_tokenizer().count(context_text),
            "selected_sources": ["diag-project-a:turn-001"],
            "runtime_trace": {"variant_id": variant_id, "mode": "diagnostic"},
            "patch_diff": patch_payload.decode("utf-8"),
            "original_files": [
                {"path": "src/retry.py", "content": original_file_payload}
            ],
            "patched_files": [
                {
                    "path": "src/retry.py",
                    "content": patched_file_payload,
                }
            ],
            "test_result": {
                "full_suite_passed": full_suite_passed,
                "passed": int(full_suite_passed),
                "failed": int(not full_suite_passed),
                "exit_code": 0 if full_suite_passed else 1,
                "timed_out": False,
                "tests": [
                    {
                        "name": "test_runtime_contract",
                        "status": test_status,
                        "duration_ms": 1,
                    }
                ],
            },
            "sandbox": _floor_sandbox_evidence(manifest),
            "provider_traces": provider_traces,
            "latency_ms": {"total": 10, "stages": {"retrieval": 2, "sandbox": 3}},
            "attempt_outcome": (
                {"status": "completed", "stage": "complete", "code": "success"}
                if full_suite_passed
                else {
                    "status": "adverse",
                    "stage": "hidden_test",
                    "code": "hidden_tests_failed",
                }
            ),
            "failure": None,
        }
    return payloads


def build_floor_runner_output_loader(
    manifest: dict[str, object],
    *,
    payloads: dict[str, dict[str, object]] | None = None,
    attempts_by_variant: dict[str, list[dict[str, object]]] | None = None,
) -> Any:
    manifest_sha256 = canonical_sha256(manifest)
    payloads = copy.deepcopy(payloads or build_floor_runner_payloads(manifest))
    entries = []
    registration_order = 0
    for slot in manifest["execution_order"]:
        variant_id = slot["variant_id"]
        attempts = (
            attempts_by_variant.get(variant_id)
            if attempts_by_variant is not None
            else None
        ) or [payloads[variant_id]]
        for attempt_offset, output in enumerate(attempts):
            outcome = output.get("attempt_outcome", {})
            state = "accepted"
            if outcome == {
                "status": "invalidated",
                "stage": "sandbox",
                "code": "technical_failure",
            }:
                state = "invalidated_technical"
            elif outcome == {
                "status": "invalidated",
                "stage": "aborted",
                "code": "manual_abort",
            }:
                state = "invalidated_abort"
            entries.append(
                {
                    "slot_index": slot["slot_index"],
                    "variant_id": variant_id,
                    "attempt_no": slot["repetition"] + attempt_offset,
                    "registration_order": registration_order,
                    "finalization_state": state,
                    "execution_manifest_sha256": manifest_sha256,
                    "runner_output_sha256": canonical_sha256(output),
                    "output": output,
                }
            )
            registration_order += 1
    snapshot = {
        "authority_kind": "test_only_trusted_finalized_runner_output_loader",
        "authority_state": "finalized",
        "execution_manifest_sha256": manifest_sha256,
        "entry_count": len(entries),
        "population_sha256": canonical_sha256(entries),
        "entries": entries,
        "test_only_simulation_marker": "TEST_ONLY_FAKE_RUNNER_OUTPUTS_NOT_PUBLIC_EVIDENCE",
    }
    return build_test_only_finalized_runner_output_authority(
        manifest_sha256=manifest_sha256,
        snapshot=snapshot,
    )


def _floor_sandbox_evidence(manifest: dict[str, object]) -> dict[str, object]:
    evaluator = manifest["evaluator_contract"]
    execution_user = evaluator["execution_user"]
    resources = evaluator["resource_limits"]
    isolation = evaluator["isolation_flags"]
    host_paths = evaluator["host_path_policy"]
    return {
        "platform": evaluator["platform"],
        "image_digest": evaluator["image_digest"],
        "base_image_digest": evaluator["base_image_digest"],
        "uid": execution_user["uid"],
        "gid": execution_user["gid"],
        "cpus": resources["cpus"],
        "memory_bytes": resources["memory_bytes"],
        "pids": resources["pids"],
        "network_none": isolation["network"] == "none",
        "read_only_root": isolation["read_only_root"],
        "drop_all_capabilities": isolation["drop_all_capabilities"],
        "no_new_privileges": isolation["no_new_privileges"],
        "tmp_is_tmpfs": isolation["tmp_is_tmpfs"],
        "tmpfs_size_bytes": resources["tmpfs_size_bytes"],
        "repository_mount_mode": isolation["repository_mount_mode"],
        "hidden_test_mount_mode": isolation["hidden_test_mount_mode"],
        "repository_root_canonical": True,
        "hidden_test_root_canonical": True,
        "roots_distinct": host_paths["repository_and_hidden_tests_distinct"],
        "wall_timeout_seconds": resources["wall_timeout_seconds"],
    }
