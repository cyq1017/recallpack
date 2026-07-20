from __future__ import annotations

import copy
import difflib
import hashlib
import hmac
import json
import re
import secrets
from dataclasses import asdict, dataclass
from typing import Any, Mapping

from recallpack.budget import canonical_json
from recallpack.evidence_authority import (
    TestOnlyTrustedRetainedAttemptLoader,
    _seal_production_retained_attempt_snapshot,
)
from recallpack.evidence import (
    validate_aggregate_report,
    validate_evaluation_run,
    validate_evidence_manifest,
    validate_execution_manifest,
)
from recallpack.isolation import (
    IsolatedExecutionBinding,
    IsolatedSuiteResult,
    ProductionExecutionIdentity,
    has_valid_production_execution_receipt,
)
from recallpack.tokenization import default_tokenizer


_RUN_ID_PATTERN = re.compile(r"^eval_[A-Za-z0-9]+$")
_SHA256_PATTERN = re.compile(r"^[a-f0-9]{64}$")
_PRODUCTION_RUNNER_AUTHORITY_KEY = secrets.token_bytes(32)
_FLOOR_CLAIM_STATEMENT = (
    "The frozen runtime and evaluator contract executed deterministically."
)
_FLOOR_RERUN_COMMAND = (
    "PYTHONPATH=src .venv/bin/python3 -m unittest tests.test_hero_evaluation"
)
_FLOOR_LIMITATIONS = (
    "Floor is diagnostic-only.",
    "No live or superiority claim is allowed.",
)
_RUNNER_FIELDS = frozenset(
    {
        "run_id",
        "variant_id",
        "full_suite_passed",
        "stdout",
        "stderr",
        "context_text",
        "context_sha256",
        "context_bytes",
        "exact_token_count",
        "selected_sources",
        "runtime_trace",
        "patch_diff",
        "original_files",
        "patched_files",
        "test_result",
        "sandbox",
        "provider_traces",
        "latency_ms",
        "attempt_outcome",
        "failure",
    }
)


@dataclass(frozen=True)
class _TestOnlyFinalizedRunnerOutputAuthority:
    _manifest_sha256: str
    _snapshot_bytes: bytes

    def __init__(self, manifest_sha256: str, snapshot: Mapping[str, Any]) -> None:
        object.__setattr__(self, "_manifest_sha256", manifest_sha256)
        object.__setattr__(
            self,
            "_snapshot_bytes",
            canonical_json(copy.deepcopy(dict(snapshot))).encode("utf-8"),
        )

    def load_finalized_runner_outputs(
        self,
        execution_manifest_sha256: str,
    ) -> dict[str, Any]:
        if execution_manifest_sha256 != self._manifest_sha256:
            raise ValueError("test-only runner authority manifest binding mismatch")
        return json.loads(self._snapshot_bytes)


@dataclass(frozen=True)
class _ProductionFinalizedRunnerOutputAuthority:
    _manifest_sha256: str
    _snapshot_bytes: bytes
    _hmac_sha256: str

    def load_finalized_runner_outputs(
        self,
        execution_manifest_sha256: str,
    ) -> dict[str, Any]:
        if execution_manifest_sha256 != self._manifest_sha256:
            raise ValueError("production runner authority manifest binding mismatch")
        expected_hmac = hmac.new(
            _PRODUCTION_RUNNER_AUTHORITY_KEY,
            self._snapshot_bytes,
            hashlib.sha256,
        ).hexdigest()
        if not hmac.compare_digest(self._hmac_sha256, expected_hmac):
            raise ValueError("production runner authority authentication failed")
        return json.loads(self._snapshot_bytes)


class ProductionRunnerOutputJournal:
    """Evaluator-owned append-only journal for production runner outputs."""

    def __init__(self, execution_manifest_sha256: str) -> None:
        if _SHA256_PATTERN.fullmatch(execution_manifest_sha256) is None:
            raise ValueError("production runner journal manifest hash is invalid")
        self._manifest_sha256 = execution_manifest_sha256
        self._entries: list[dict[str, Any]] = []
        self._finalized = False

    def append(
        self,
        *,
        scenario_id: str,
        slot_index: int,
        variant_id: str,
        attempt_no: int,
        output: Mapping[str, Any],
        isolated_result: IsolatedSuiteResult | None = None,
        expected_identity: ProductionExecutionIdentity | None = None,
    ) -> None:
        if self._finalized:
            raise RuntimeError("production runner journal is finalized")
        if (
            not scenario_id
            or not variant_id
            or not isinstance(slot_index, int)
            or isinstance(slot_index, bool)
            or slot_index < 0
            or not isinstance(attempt_no, int)
            or isinstance(attempt_no, bool)
            or attempt_no < 1
            or not isinstance(output, Mapping)
            or output.get("variant_id") != variant_id
        ):
            raise ValueError("production runner journal entry identity is invalid")
        binding = output.get("runtime_trace")
        binding = binding.get("execution_binding") if isinstance(binding, Mapping) else None
        journal_identity = {
            "execution_manifest_sha256": self._manifest_sha256,
            "scenario_id": scenario_id,
            "slot_index": slot_index,
            "attempt_no": attempt_no,
        }
        if (
            not isinstance(binding, Mapping)
            or binding.get("authority_mode")
            not in {"production_docker", "patch_not_executed"}
            or binding.get("variant_id") != variant_id
            or any(binding.get(key) != value for key, value in journal_identity.items())
        ):
            raise ValueError(
                "production runner journal requires a matching production execution binding"
            )
        if any(
            _SHA256_PATTERN.fullmatch(str(binding.get(key) or "")) is None
            for key in (
                "repository_snapshot_sha256",
                "frozen_hidden_test_tree_sha256",
            )
        ):
            raise ValueError(
                "production runner journal requires frozen source digests"
            )
        _validate_production_runner_receipt(
            output=output,
            serialized_binding=binding,
            isolated_result=isolated_result,
            expected_identity=expected_identity,
        )
        state = _runner_output_finalization_state(output)
        if state is None:
            raise ValueError("production runner journal outcome is invalid")
        prior = [entry for entry in self._entries if entry["slot_index"] == slot_index]
        if prior:
            previous = prior[-1]
            if attempt_no <= previous["attempt_no"]:
                raise ValueError("production runner attempts must increase within a slot")
            if previous["finalization_state"] == "accepted":
                raise ValueError("accepted production runner attempt cannot be replaced")
            if previous["finalization_state"] == "invalidated_abort":
                raise ValueError("manual-abort production runner attempt cannot be replaced")
            if (
                previous["finalization_state"] == "invalidated_technical"
                and state != "accepted"
            ):
                raise ValueError(
                    "technical production runner attempt requires an accepted replacement"
                )
        frozen_output = copy.deepcopy(dict(output))
        self._entries.append(
            {
                "slot_index": slot_index,
                "variant_id": variant_id,
                "attempt_no": attempt_no,
                "registration_order": len(self._entries),
                "finalization_state": state,
                "execution_manifest_sha256": self._manifest_sha256,
                "runner_output_sha256": _canonical_sha256(frozen_output),
                "output": frozen_output,
            }
        )

    def finalize(self) -> _ProductionFinalizedRunnerOutputAuthority:
        if self._finalized:
            raise RuntimeError("production runner journal is finalized")
        self._finalized = True
        snapshot = {
            "authority_kind": "production_finalized_runner_output_authority",
            "authority_state": "finalized",
            "execution_manifest_sha256": self._manifest_sha256,
            "entry_count": len(self._entries),
            "population_sha256": _canonical_sha256(self._entries),
            "entries": copy.deepcopy(self._entries),
        }
        snapshot_bytes = _canonical_json_bytes(snapshot)
        return _ProductionFinalizedRunnerOutputAuthority(
            _manifest_sha256=self._manifest_sha256,
            _snapshot_bytes=snapshot_bytes,
            _hmac_sha256=hmac.new(
                _PRODUCTION_RUNNER_AUTHORITY_KEY,
                snapshot_bytes,
                hashlib.sha256,
            ).hexdigest(),
        )


def _validate_production_runner_receipt(
    *,
    output: Mapping[str, Any],
    serialized_binding: Mapping[str, Any],
    isolated_result: IsolatedSuiteResult | None,
    expected_identity: ProductionExecutionIdentity | None,
) -> None:
    if (
        type(isolated_result) is not IsolatedSuiteResult
        or type(expected_identity) is not ProductionExecutionIdentity
        or not has_valid_production_execution_receipt(
            isolated_result,
            expected_identity=expected_identity,
        )
    ):
        raise ValueError(
            "production runner journal requires an authenticated execution receipt"
        )
    binding = isolated_result.execution_binding
    patched_files = output.get("patched_files")
    if (
        type(binding) is not IsolatedExecutionBinding
        or dict(serialized_binding) != asdict(binding)
        or output.get("stdout") != isolated_result.stdout
        or output.get("stderr") != isolated_result.stderr
        or (
            binding.authority_mode == "production_docker"
            and (
                not isinstance(patched_files, list)
                or _canonical_sha256(patched_files) != binding.patch_sha256
            )
        )
    ):
        raise ValueError("production runner envelope does not match its execution receipt")
    outcome = output.get("attempt_outcome")
    if binding.authority_mode == "production_docker":
        if isolated_result.blocked:
            expected_outcome = {
                "status": "invalidated",
                "stage": "sandbox",
                "code": "technical_failure",
            }
            expected_failure = {
                "code": isolated_result.failure_code,
                "detail": (
                    "isolated evaluator did not produce a closed test result; "
                    f"cleanup_attempted={isolated_result.cleanup_attempted}; "
                    f"cleanup_succeeded={isolated_result.cleanup_succeeded}"
                ),
                "evidence_sha256": hashlib.sha256(
                    (isolated_result.stdout + "\n" + isolated_result.stderr).encode(
                        "utf-8"
                    )
                ).hexdigest(),
            }
            valid = (
                output.get("full_suite_passed") is None
                and output.get("test_result") is None
                and outcome == expected_outcome
                and output.get("failure") == expected_failure
            )
        else:
            result_payload = isolated_result.json_result
            passed = (
                result_payload.get("full_suite_passed")
                if isinstance(result_payload, Mapping)
                else None
            )
            expected_outcome = (
                {"status": "completed", "stage": "complete", "code": "success"}
                if passed is True
                else {
                    "status": "adverse",
                    "stage": "hidden_test",
                    "code": "hidden_tests_failed",
                }
            )
            valid = (
                isinstance(passed, bool)
                and output.get("full_suite_passed") is passed
                and output.get("test_result") == result_payload
                and outcome == expected_outcome
            )
    elif binding.authority_mode == "patch_not_executed":
        outcome_tuple = (
            outcome.get("status"),
            outcome.get("stage"),
            outcome.get("code"),
        ) if isinstance(outcome, Mapping) else None
        expected_code = (
            "empty_patch"
            if isolated_result.failure_code == "empty_patch"
            else "patch_rejected"
        )
        valid = (
            isolated_result.blocked
            and isolated_result.exit_code is None
            and isolated_result.json_result is None
            and output.get("full_suite_passed") is None
            and output.get("test_result") is None
            and output.get("patch_diff") == ""
            and output.get("original_files") == []
            and output.get("patched_files") == []
            and output.get("failure") is None
            and outcome_tuple
            == ("adverse", "patch_generation", expected_code)
        )
    else:
        valid = False
    if not valid:
        raise ValueError("production runner envelope outcome contradicts its receipt")


def build_test_only_finalized_runner_output_authority(
    *,
    manifest_sha256: str,
    snapshot: Mapping[str, Any],
) -> Any:
    """Build a non-public simulation authority for validator tests only."""
    if (
        snapshot.get("authority_kind")
        != "test_only_trusted_finalized_runner_output_loader"
        or snapshot.get("test_only_simulation_marker")
        != "TEST_ONLY_FAKE_RUNNER_OUTPUTS_NOT_PUBLIC_EVIDENCE"
    ):
        _fail(
            "invalid_retained_population",
            "test-only runner authority requires an explicit simulation marker",
        )
    return _TestOnlyFinalizedRunnerOutputAuthority(
        manifest_sha256,
        snapshot,
    )


def run_v4_floor_evidence_pipeline(
    *,
    manifest: Mapping[str, Any],
    finalized_runner_output_loader: Any,
    input_artifact_bytes: Mapping[str, bytes],
    source_ledgers: Mapping[str, Mapping[str, Any]],
    relation_label_ledgers: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    frozen_manifest = copy.deepcopy(dict(manifest))
    artifact_bytes = _copy_artifact_bytes(input_artifact_bytes)
    validate_execution_manifest(
        frozen_manifest,
        artifact_bytes=artifact_bytes,
        source_ledgers=source_ledgers,
    )
    if frozen_manifest.get("descope_rung") != "Floor":
        _fail("invalid_rung_grid", "formal diagnostic pipeline requires Floor")
    _validate_floor_claim_declaration(frozen_manifest)

    execution_order = frozen_manifest.get("execution_order")
    variants = frozen_manifest.get("variants")
    if (
        not isinstance(execution_order, list)
        or not isinstance(variants, list)
        or len(execution_order) != len(variants)
    ):
        _fail("invalid_rung_grid", "execution manifest must define the Floor grid")

    manifest_hash = _canonical_sha256(frozen_manifest)
    runner_snapshot, runner_attempts, population_complete = (
        _load_finalized_runner_outputs(
        finalized_runner_output_loader,
        manifest_hash=manifest_hash,
        execution_order=execution_order,
        variants=variants,
        )
    )
    test_only_simulation = (
        runner_snapshot.get("test_only_simulation_marker") is not None
    )

    runs: list[dict[str, Any]] = []
    for slot, entry, output in runner_attempts:
        run, output_bytes = _build_floor_run(
            frozen_manifest,
            slot,
            output,
            attempt_no=entry["attempt_no"],
            production_evidence=not test_only_simulation,
        )
        _merge_artifact_bytes(artifact_bytes, output_bytes)
        source_ledger = source_ledgers.get(run["scenario_id"])
        if not isinstance(source_ledger, Mapping):
            _fail("invalid_run_reference", "run scenario source ledger is missing")
        relation_ledger = relation_label_ledgers.get(run["scenario_id"])
        validate_evaluation_run(
            run,
            frozen_manifest,
            artifact_bytes=artifact_bytes,
            source_ledger=source_ledger,
            relation_label_ledger=(
                relation_ledger if isinstance(relation_ledger, Mapping) else None
            ),
        )
        runs.append(run)

    for run in runs:
        run_artifact_id = f"run_{run['run_id']}"
        run_bytes = _canonical_json_bytes(run)
        if run_artifact_id in artifact_bytes:
            _fail("invalid_output_catalog", "run artifact ID collides")
        artifact_bytes[run_artifact_id] = run_bytes

    retained_attempt_loader = _build_retained_attempt_loader(
        manifest_hash,
        runs,
        runner_snapshot,
        test_only_simulation=test_only_simulation,
    )
    incomplete_population = not population_complete
    aggregate = None
    if not incomplete_population:
        aggregate = _build_structural_aggregate(frozen_manifest, runs)
        aggregate_bytes = _canonical_json_bytes(aggregate)
        if aggregate["aggregate_id"] in artifact_bytes:
            _fail("invalid_output_catalog", "aggregate artifact ID collides")
        artifact_bytes[aggregate["aggregate_id"]] = aggregate_bytes
        validate_aggregate_report(
            aggregate,
            execution_manifest=frozen_manifest,
            retained_attempt_loader=retained_attempt_loader,
            artifact_bytes=artifact_bytes,
            source_ledgers=source_ledgers,
            relation_label_ledgers=relation_label_ledgers,
        )

    evidence_manifest = None
    if not incomplete_population:
        evidence_manifest = _build_final_evidence_manifest(
            frozen_manifest,
            runs,
            aggregate,
            artifact_bytes,
            test_only_simulation=test_only_simulation,
        )
        validate_evidence_manifest(
            evidence_manifest,
            frozen_manifest,
            retained_attempt_loader=retained_attempt_loader,
            artifact_bytes=artifact_bytes,
            source_ledgers=source_ledgers,
            relation_label_ledgers=relation_label_ledgers,
        )
    packet = {
        "record_type": "v4_floor_evidence_packet",
        "evidence_artifacts_emitted": True,
        "execution_manifest_sha256": manifest_hash,
        "runs": runs,
        "aggregate_report": aggregate,
        "evidence_manifest": evidence_manifest,
        "artifact_bytes": artifact_bytes,
        "retained_attempt_loader": retained_attempt_loader,
        "runner_authority_kind": runner_snapshot["authority_kind"],
        "evidence_status": (
            "incomplete_retained_population"
            if incomplete_population
            else (
                "partial_test_only_evidence"
                if test_only_simulation
                else "final_production_evidence"
            )
        ),
    }
    simulation_marker = runner_snapshot.get("test_only_simulation_marker")
    if simulation_marker is not None:
        packet["test_only_simulation_marker"] = simulation_marker
    return packet


def _build_floor_run(
    manifest: Mapping[str, Any],
    slot: Mapping[str, Any],
    output: Any,
    *,
    attempt_no: int | None = None,
    production_evidence: bool = False,
) -> tuple[dict[str, Any], dict[str, bytes]]:
    if not isinstance(output, Mapping) or set(output) != _RUNNER_FIELDS:
        _fail("invalid_run_reference", "runner output must use the closed envelope")
    variant_id = slot.get("variant_id")
    run_id = output.get("run_id")
    if (
        output.get("variant_id") != variant_id
        or not isinstance(run_id, str)
        or _RUN_ID_PATTERN.fullmatch(run_id) is None
    ):
        _fail("invalid_run_reference", "runner output identity is invalid")
    resolved_attempt_no = slot["repetition"] if attempt_no is None else attempt_no
    _validate_runner_execution_identity(
        output.get("runtime_trace"),
        manifest=manifest,
        slot=slot,
        attempt_no=resolved_attempt_no,
        production_evidence=production_evidence,
    )

    context_text = output.get("context_text")
    if not isinstance(context_text, str):
        _fail("invalid_context_evidence", "model-visible context must be text")
    context_bytes = context_text.encode("utf-8")
    context_sha256 = _sha256(context_bytes)
    exact_token_count = default_tokenizer().count(context_text)
    if (
        output.get("context_sha256") != context_sha256
        or output.get("context_bytes") != len(context_bytes)
        or output.get("exact_token_count") != exact_token_count
    ):
        _fail(
            "invalid_context_evidence",
            "runner context hash, bytes, and exact token count must recompute",
        )

    outcome = copy.deepcopy(output.get("attempt_outcome"))
    if not isinstance(outcome, Mapping):
        _fail("invalid_run_outcome", "runner attempt outcome is missing")
    outcome_tuple = (
        outcome.get("status"),
        outcome.get("stage"),
        outcome.get("code"),
    )
    allowed_outcomes = {
        ("completed", "complete", "success"),
        ("adverse", "hidden_test", "hidden_tests_failed"),
        ("adverse", "patch_generation", "patch_rejected"),
        ("adverse", "patch_generation", "empty_patch"),
        ("invalidated", "sandbox", "technical_failure"),
        ("invalidated", "aborted", "manual_abort"),
    }
    if outcome_tuple not in allowed_outcomes:
        _fail("invalid_run_outcome", "runner attempt outcome is not in the truth table")

    patch_expected = outcome_tuple not in {
        ("adverse", "patch_generation", "patch_rejected"),
        ("adverse", "patch_generation", "empty_patch"),
        ("invalidated", "aborted", "manual_abort"),
    }
    if patch_expected:
        original_files, patch_files, original_file_payloads, patch_file_payloads = (
            _normalize_patch_files(manifest, run_id, output)
        )
    else:
        if any(
            (
                output.get("patch_diff") != "",
                output.get("original_files") != [],
                output.get("patched_files") != [],
            )
        ):
            _fail("invalid_patch_result", "rejected patch attempt must not carry patch artifacts")
        original_files = []
        patch_files = []
        original_file_payloads = []
        patch_file_payloads = []

    full_suite_passed = output.get("full_suite_passed")
    test_result = output.get("test_result")
    test_expected = outcome_tuple in {
        ("completed", "complete", "success"),
        ("adverse", "hidden_test", "hidden_tests_failed"),
    }
    if test_expected:
        if not isinstance(full_suite_passed, bool) or not isinstance(test_result, Mapping):
            _fail("invalid_test_result", "runner test result is malformed")
        if test_result.get("full_suite_passed") is not full_suite_passed:
            _fail("invalid_test_result", "runner suite result is contradictory")
        if full_suite_passed is not (outcome_tuple[0] == "completed"):
            _fail("invalid_run_outcome", "runner outcome contradicts suite status")
    elif full_suite_passed is not None or test_result is not None:
        _fail("invalid_test_result", "unexecuted attempt must not carry a test result")

    failure = copy.deepcopy(output.get("failure"))
    technical = outcome_tuple == ("invalidated", "sandbox", "technical_failure")
    manual_abort = outcome_tuple == ("invalidated", "aborted", "manual_abort")
    if technical or manual_abort:
        if not isinstance(failure, Mapping):
            _fail("invalid_failure_code", "invalidated attempt requires failure evidence")
        expected_failure_code = "manual_abort" if manual_abort else None
        if expected_failure_code is not None and failure.get("code") != expected_failure_code:
            _fail("invalid_failure_code", "manual abort failure evidence is invalid")
    elif failure is not None:
        _fail("invalid_failure_code", "non-technical attempt cannot carry failure evidence")
    output_catalog, output_bytes = _build_run_output_catalog(
        run_id,
        output,
        context_bytes,
        original_file_payloads,
        patch_file_payloads,
    )
    provider_traces = copy.deepcopy(output.get("provider_traces"))
    if not isinstance(provider_traces, list):
        _fail("invalid_provider_trace", "provider traces must be a list")
    usage = _provider_usage(provider_traces)
    normalized_test_result = None
    if test_expected:
        normalized_tests = _normalize_tests(
            test_result.get("tests"),
            evidence_artifact_id=f"{run_id}_test_result",
        )
        normalized_test_result = {
            "full_suite_passed": full_suite_passed,
            "passed": test_result.get("passed"),
            "failed": test_result.get("failed"),
            "exit_code": test_result.get("exit_code"),
            "timed_out": test_result.get("timed_out"),
            "sandbox": copy.deepcopy(output.get("sandbox")),
            "test_result_artifact_id": f"{run_id}_test_result",
            "stdout_artifact_id": f"{run_id}_stdout",
            "stderr_artifact_id": f"{run_id}_stderr",
            "tests": normalized_tests,
        }
    patch_record = None
    if patch_expected:
        patch_diff_id = f"{run_id}_patch_diff"
        patch_diff_record = output_catalog[patch_diff_id]
        patch_record = {
            "accepted": True,
            "diff_artifact_id": patch_diff_id,
            "diff_sha256": patch_diff_record["sha256"],
            "validation_status": "accepted",
            "original_files": original_files,
            "files": patch_files,
        }
    elif outcome_tuple[2] == "patch_rejected":
        patch_record = {
            "accepted": False,
            "diff_artifact_id": None,
            "diff_sha256": None,
            "validation_status": "rejected",
            "original_files": [],
            "files": [],
        }
    run = {
        "record_type": "evaluation_run",
        "run_id": run_id,
        "manifest_version": manifest["manifest_version"],
        "semantic_rules_version": manifest["semantic_rules_version"],
        "execution_manifest_sha256": _canonical_sha256(manifest),
        "scenario_id": slot["scenario_slot"],
        "variant_id": variant_id,
        "slot_index": slot["slot_index"],
        "attempt_no": resolved_attempt_no,
        "designation": (
            "invalidated_technical"
            if technical
            else "invalidated_abort" if manual_abort else "diagnostic"
        ),
        "outcome": outcome,
        "context_evidence": {
            "artifact_id": f"{run_id}_context",
            "sha256": context_sha256,
            "exact_token_count": exact_token_count,
            "tokenizer": copy.deepcopy(manifest["comparison_contract"]["tokenizer"]),
            "budget_policy": (
                "unbounded_reference"
                if variant_id == "raw_full_history"
                else "exact_512_max"
            ),
        },
        "selected_sources": copy.deepcopy(output.get("selected_sources")),
        "metrics": _floor_unscored_metrics(output.get("selected_sources")),
        "relation_opportunities": [],
        "patch": patch_record,
        "test_result": normalized_test_result,
        "usage": usage,
        "latency_ms": copy.deepcopy(output.get("latency_ms")),
        "provider_traces": provider_traces,
        "run_output_artifact_catalog": output_catalog,
        "artifact_hashes": {
            artifact_id: record["sha256"]
            for artifact_id, record in output_catalog.items()
        },
        "failure": failure,
    }
    return run, output_bytes


def _validate_runner_execution_identity(
    runtime_trace: Any,
    *,
    manifest: Mapping[str, Any],
    slot: Mapping[str, Any],
    attempt_no: int,
    production_evidence: bool = False,
) -> None:
    if not isinstance(runtime_trace, Mapping):
        _fail("invalid_run_reference", "runner runtime trace must be an object")
    binding = runtime_trace.get("execution_binding")
    if binding is None:
        if production_evidence:
            _fail(
                "invalid_run_reference",
                "production runner output requires an execution binding",
            )
        return
    if not isinstance(binding, Mapping):
        _fail("invalid_run_reference", "runner execution binding must be an object")
    identity_fields = (
        "execution_manifest_sha256",
        "scenario_id",
        "slot_index",
        "attempt_no",
    )
    authority_mode = binding.get("authority_mode")
    binding_has_production_identity = any(
        binding.get(key) is not None for key in identity_fields
    )
    if authority_mode in {
        "test_only_injected_runner",
        "test_only_patch_not_executed",
    }:
        if production_evidence:
            _fail(
                "invalid_run_reference",
                "production evidence cannot use a test-only execution binding",
            )
        if binding_has_production_identity:
            _fail(
                "invalid_run_reference",
                "test-only execution binding cannot carry production identity",
            )
        return
    if authority_mode not in {"production_docker", "patch_not_executed"}:
        _fail("invalid_run_reference", "runner execution authority mode is invalid")
    expected = {
        "variant_id": slot.get("variant_id"),
        "execution_manifest_sha256": _canonical_sha256(manifest),
        "scenario_id": slot.get("scenario_slot"),
        "slot_index": slot.get("slot_index"),
        "attempt_no": attempt_no,
    }
    if any(binding.get(key) != value for key, value in expected.items()):
        _fail(
            "invalid_run_reference",
            "production execution binding does not match the current manifest slot attempt",
        )


def _build_run_output_catalog(
    run_id: str,
    output: Mapping[str, Any],
    context_bytes: bytes,
    original_file_payloads: list[tuple[str, str, bytes]],
    patch_file_payloads: list[tuple[str, str, bytes]],
) -> tuple[dict[str, dict[str, Any]], dict[str, bytes]]:
    payloads = {
        f"{run_id}_runtime_trace": _canonical_json_bytes(output["runtime_trace"]),
        f"{run_id}_context": context_bytes,
        f"{run_id}_stdout": _text_bytes(output["stdout"], "stdout"),
        f"{run_id}_stderr": _text_bytes(output["stderr"], "stderr"),
    }
    kinds = {
        f"{run_id}_runtime_trace": "runtime_trace",
        f"{run_id}_context": "model_visible_context",
        f"{run_id}_stdout": "stdout",
        f"{run_id}_stderr": "stderr",
    }
    names = {
        f"{run_id}_runtime_trace": "trace.json",
        f"{run_id}_context": "context.txt",
        f"{run_id}_stdout": "stdout.txt",
        f"{run_id}_stderr": "stderr.txt",
    }
    if output["patch_diff"]:
        artifact_id = f"{run_id}_patch_diff"
        payloads[artifact_id] = _text_bytes(output["patch_diff"], "patch diff")
        kinds[artifact_id] = "patch_diff"
        names[artifact_id] = "patch.diff"
    if output["test_result"] is not None:
        artifact_id = f"{run_id}_test_result"
        payloads[artifact_id] = _canonical_json_bytes(output["test_result"])
        kinds[artifact_id] = "test_result"
        names[artifact_id] = "test-result.json"
    for artifact_id, relative_path, payload in original_file_payloads:
        payloads[artifact_id] = payload
        kinds[artifact_id] = "original_file"
        names[artifact_id] = f"original-files/{relative_path}"
    for artifact_id, relative_path, payload in patch_file_payloads:
        payloads[artifact_id] = payload
        kinds[artifact_id] = "patched_file"
        names[artifact_id] = f"patched-files/{relative_path}"
    catalog = {
        artifact_id: _artifact_record(
            kinds[artifact_id],
            f"runs/{run_id}/{names[artifact_id]}",
            payload,
        )
        for artifact_id, payload in payloads.items()
    }
    return catalog, payloads


def _build_retained_attempt_loader(
    manifest_sha256: str,
    runs: list[dict[str, Any]],
    runner_snapshot: Mapping[str, Any],
    *,
    test_only_simulation: bool,
) -> Any:
    runner_entries = runner_snapshot["entries"]
    if len(runner_entries) != len(runs):
        _fail("invalid_retained_population", "runner and evidence populations differ")
    entries = [
        {
            "run_artifact_id": f"run_{run['run_id']}",
            "run_id": run["run_id"],
            "canonical_run_sha256": _canonical_sha256(run),
            "slot_index": run["slot_index"],
            "attempt_no": run["attempt_no"],
            "designation": run["designation"],
            "registration_order": index,
            "execution_manifest_sha256": manifest_sha256,
            "finalization_state": (
                run["designation"]
                if run["designation"] in {"invalidated_technical", "invalidated_abort"}
                else "accepted"
            ),
        }
        for index, run in enumerate(runs)
    ]
    for runner_entry, evidence_entry in zip(runner_entries, entries):
        if (
            runner_entry["slot_index"] != evidence_entry["slot_index"]
            or runner_entry["attempt_no"] != evidence_entry["attempt_no"]
            or runner_entry["registration_order"]
            != evidence_entry["registration_order"]
            or runner_entry["finalization_state"]
            != evidence_entry["finalization_state"]
        ):
            _fail(
                "invalid_retained_population",
                "evidence population must preserve the finalized runner journal order",
            )
    snapshot = {
        "authority_kind": (
            "test_only_sealed_retained_attempt_authority"
            if test_only_simulation
            else "production_append_only_attempt_journal"
        ),
        "authority_state": "finalized",
        "execution_manifest_sha256": manifest_sha256,
        "entry_count": len(entries),
        "population_sha256": _canonical_sha256(entries),
        "entries": entries,
    }
    if test_only_simulation:
        snapshot["simulation_marker"] = "test_only_sealed_retained_attempt_authority"
        return TestOnlyTrustedRetainedAttemptLoader(snapshot)
    return _seal_production_retained_attempt_snapshot(snapshot)


def _build_structural_aggregate(
    manifest: Mapping[str, Any],
    runs: list[dict[str, Any]],
) -> dict[str, Any]:
    declarations = manifest["claim_declarations"]
    accepted_runs = [
        run
        for run in runs
        if run["designation"] not in {"invalidated_technical", "invalidated_abort"}
    ]
    run_ids = [run["run_id"] for run in accepted_runs]
    n = len(accepted_runs)
    return {
        "record_type": "aggregate_report",
        "aggregate_id": "agg_FloorStructural",
        "manifest_version": manifest["manifest_version"],
        "semantic_rules_version": manifest["semantic_rules_version"],
        "execution_manifest_sha256": _canonical_sha256(manifest),
        "claim_id": declarations[0]["claim_id"],
        "claim_type": "structural_runtime",
        "scope": {
            "selection_rule": "all_accepted_runs_in_scope",
            "designation": "diagnostic",
            "scenario_ids": list(manifest["scenario_slots"]),
            "variant_ids": list(manifest["variants"]),
        },
        "run_ids": run_ids,
        "adverse_run_ids": [
            run["run_id"]
            for run in accepted_runs
            if run["outcome"]["status"] == "adverse"
        ],
        "metrics": [
            {
                "metric_id": "runtime_contract_success",
                "n": n,
                "numerator": n,
                "denominator": n,
                "rate": 1.0,
            }
        ],
        "limitations": [
            "Floor is deterministic diagnostic evidence only; no live or superiority claim.",
            "Retrieval quality metrics are unscored schema placeholders at Floor.",
        ],
        "artifact_hashes": {
            "execution_manifest": _canonical_sha256(manifest),
            **{
                f"run:{run['run_id']}": _canonical_sha256(run)
                for run in accepted_runs
            },
        },
    }


def _build_final_evidence_manifest(
    manifest: Mapping[str, Any],
    runs: list[dict[str, Any]],
    aggregate: dict[str, Any] | None,
    artifact_bytes: Mapping[str, bytes],
    *,
    test_only_simulation: bool,
) -> dict[str, Any]:
    output_catalog: dict[str, dict[str, Any]] = {}
    for run in runs:
        for artifact_id, record in run["run_output_artifact_catalog"].items():
            existing = output_catalog.get(artifact_id)
            if existing is not None and existing != record:
                _fail("invalid_output_catalog", "run output artifact collision")
            output_catalog[artifact_id] = copy.deepcopy(record)
        run_artifact_id = f"run_{run['run_id']}"
        output_catalog[run_artifact_id] = _artifact_record(
            "evaluation_run",
            f"runs/{run['run_id']}.json",
            artifact_bytes[run_artifact_id],
        )
    if not test_only_simulation:
        if aggregate is None:
            _fail("incomplete_final_evidence", "final evidence requires an aggregate")
        output_catalog[aggregate["aggregate_id"]] = _artifact_record(
            "aggregate_report",
            f"aggregates/{aggregate['aggregate_id']}.json",
            artifact_bytes[aggregate["aggregate_id"]],
        )
    declaration = manifest["claim_declarations"][0]
    return {
        "record_type": "evidence_manifest",
        "evidence_manifest_id": "evidence_FloorFinal",
        "evidence_manifest_version": "v4",
        "created_at": manifest["created_at"],
        "semantic_rules_version": "4.0",
        "execution_manifest_version": manifest["manifest_version"],
        "execution_manifest_sha256": _canonical_sha256(manifest),
        "previous_evidence_manifest_sha256": None,
        "status": "partial" if test_only_simulation else "final",
        "output_artifact_catalog": output_catalog,
        "run_ids": [run["run_id"] for run in runs],
        "aggregate_ids": [] if test_only_simulation else [aggregate["aggregate_id"]],
        "claims": [
            {
                "claim_id": declaration["claim_id"],
                "claim_type": declaration["claim_type"],
                "activation_rule_id": declaration["activation_rule_id"],
                "status": "disabled" if test_only_simulation else "enabled",
                "decision_reason": (
                    "evidence_incomplete" if test_only_simulation else "threshold_passed"
                ),
                "statement": _FLOOR_CLAIM_STATEMENT,
                "evidence_artifact_ids": (
                    [] if test_only_simulation else [aggregate["aggregate_id"]]
                ),
                "rerunnable_command": _FLOOR_RERUN_COMMAND,
                "limitations": list(_FLOOR_LIMITATIONS),
            }
        ],
    }


def _load_finalized_runner_outputs(
    loader: Any,
    *,
    manifest_hash: str,
    execution_order: list[Any],
    variants: list[Any],
) -> tuple[
    dict[str, Any],
    list[tuple[Mapping[str, Any], Mapping[str, Any], Mapping[str, Any]]],
    bool,
]:
    loader_type = type(loader)
    if loader_type not in {
        _TestOnlyFinalizedRunnerOutputAuthority,
        _ProductionFinalizedRunnerOutputAuthority,
    }:
        _fail(
            "invalid_retained_population",
            "Floor accepts only evaluator-owned finalized runner authorities",
        )
    try:
        load = getattr(loader, "load_finalized_runner_outputs")
        snapshot = load(manifest_hash)
    except Exception as exc:
        _fail(
            "invalid_retained_population",
            f"runner authority could not load: {type(exc).__name__}",
        )
    if not isinstance(snapshot, Mapping):
        _fail("invalid_retained_population", "runner authority snapshot must be an object")

    base_fields = {
        "authority_kind",
        "authority_state",
        "execution_manifest_sha256",
        "entry_count",
        "population_sha256",
        "entries",
    }
    test_only = loader_type is _TestOnlyFinalizedRunnerOutputAuthority
    expected_fields = (
        base_fields | {"test_only_simulation_marker"}
        if test_only
        else base_fields
    )
    expected_kind = (
        "test_only_trusted_finalized_runner_output_loader"
        if test_only
        else "production_finalized_runner_output_authority"
    )
    authority_kind = snapshot.get("authority_kind")
    if (
        set(snapshot) != expected_fields
        or authority_kind != expected_kind
        or snapshot.get("authority_state") != "finalized"
        or snapshot.get("execution_manifest_sha256") != manifest_hash
    ):
        _fail("invalid_retained_population", "runner authority header is invalid")
    marker = snapshot.get("test_only_simulation_marker")
    if test_only and marker != "TEST_ONLY_FAKE_RUNNER_OUTPUTS_NOT_PUBLIC_EVIDENCE":
        _fail(
            "invalid_retained_population",
            "test-only runner authority requires its simulation marker",
        )

    entries = snapshot.get("entries")
    if (
        not isinstance(entries, list)
        or snapshot.get("entry_count") != len(entries)
        or snapshot.get("population_sha256") != _canonical_sha256(entries)
        or len(entries) < len(execution_order)
    ):
        _fail("invalid_retained_population", "runner population root is invalid")

    expected_entry_fields = {
        "slot_index",
        "variant_id",
        "attempt_no",
        "registration_order",
        "finalization_state",
        "execution_manifest_sha256",
        "runner_output_sha256",
        "output",
    }
    slots_by_index: dict[int, Mapping[str, Any]] = {}
    for slot in execution_order:
        if not isinstance(slot, Mapping):
            _fail("invalid_retained_population", "runner entries and slots must be objects")
        slot_index = slot.get("slot_index")
        if not isinstance(slot_index, int) or isinstance(slot_index, bool):
            _fail("invalid_retained_population", "runner slot identity is invalid")
        if slot_index in slots_by_index:
            _fail("invalid_retained_population", "runner slot identity is duplicated")
        slots_by_index[slot_index] = slot

    attempts_by_slot: dict[int, list[Mapping[str, Any]]] = {
        slot_index: [] for slot_index in slots_by_index
    }
    retained_attempts = []
    for index, entry in enumerate(entries):
        if not isinstance(entry, Mapping):
            _fail("invalid_retained_population", "runner entry must be an object")
        slot = slots_by_index.get(entry.get("slot_index"))
        if slot is None:
            _fail("invalid_retained_population", "runner entry names an unknown slot")
        output = entry.get("output")
        variant_id = slot.get("variant_id")
        attempt_no = entry.get("attempt_no")
        expected_state = _runner_output_finalization_state(output)
        if (
            set(entry) != expected_entry_fields
            or entry.get("variant_id") != variant_id
            or entry.get("registration_order") != index
            or entry.get("finalization_state") != expected_state
            or entry.get("execution_manifest_sha256") != manifest_hash
            or not isinstance(output, Mapping)
            or entry.get("runner_output_sha256") != _canonical_sha256(output)
            or output.get("variant_id") != variant_id
            or not isinstance(attempt_no, int)
            or isinstance(attempt_no, bool)
            or attempt_no < slot.get("repetition", 1)
        ):
            _fail("invalid_retained_population", "runner entry does not match its frozen slot")
        slot_attempts = attempts_by_slot[entry["slot_index"]]
        if slot_attempts and attempt_no <= slot_attempts[-1]["attempt_no"]:
            _fail(
                "invalid_retained_population",
                "runner replacement attempts must increase within a slot",
            )
        if slot_attempts and slot_attempts[-1]["finalization_state"] == "accepted":
            _fail(
                "invalid_retained_population",
                "accepted runner attempts cannot be replaced",
            )
        if slot_attempts and slot_attempts[-1]["finalization_state"] == "invalidated_abort":
            _fail(
                "invalid_retained_population",
                "manual-abort runner attempt cannot be replaced",
            )
        if (
            slot_attempts
            and slot_attempts[-1]["finalization_state"]
            == "invalidated_technical"
            and entry["finalization_state"] != "accepted"
        ):
            _fail(
                "invalid_retained_population",
                "an invalidated runner attempt requires an accepted replacement",
            )
        slot_attempts.append(entry)
        retained_attempts.append((slot, entry, output))

    accepted_variants = set()
    population_complete = True
    for slot_index, slot in slots_by_index.items():
        slot_attempts = attempts_by_slot[slot_index]
        accepted = [
            entry for entry in slot_attempts if entry["finalization_state"] == "accepted"
        ]
        if len(accepted) > 1:
            _fail("invalid_retained_population", "runner slot has duplicate accepted attempts")
        if not accepted:
            population_complete = False
            if not slot_attempts or slot_attempts[-1]["finalization_state"] not in {
                "invalidated_technical",
                "invalidated_abort",
            }:
                _fail(
                    "invalid_retained_population",
                    "unresolved runner slot must end in an invalidated attempt",
                )
            continue
        if accepted[0] is not slot_attempts[-1]:
            _fail(
                "invalid_retained_population",
                "accepted runner replacement must close its slot",
            )
        accepted_variants.add(slot.get("variant_id"))
    if population_complete and accepted_variants != set(variants):
        _fail("invalid_rung_grid", "finalized runner population must close the Floor grid")
    return copy.deepcopy(dict(snapshot)), retained_attempts, population_complete


def _runner_output_finalization_state(output: Any) -> str | None:
    if not isinstance(output, Mapping):
        return None
    outcome = output.get("attempt_outcome")
    if outcome == {
        "status": "invalidated",
        "stage": "sandbox",
        "code": "technical_failure",
    }:
        return "invalidated_technical"
    if outcome == {
        "status": "invalidated",
        "stage": "aborted",
        "code": "manual_abort",
    }:
        return "invalidated_abort"
    return "accepted"


def _validate_floor_claim_declaration(manifest: Mapping[str, Any]) -> None:
    declarations = manifest.get("claim_declarations")
    if not isinstance(declarations, list) or len(declarations) != 1:
        _fail(
            "invalid_claim_reference",
            "Floor pipeline requires exactly one structural declaration",
        )
    declaration = declarations[0]
    if not isinstance(declaration, Mapping):
        _fail("invalid_claim_reference", "Floor claim declaration must be an object")
    expected = {
        "claim_type": "structural_runtime",
        "activation_rule_id": "structural_runtime_gate",
        "eligible_rungs": ["Full", "R1", "R2", "Floor"],
        "statement": _FLOOR_CLAIM_STATEMENT,
        "rerunnable_command": _FLOOR_RERUN_COMMAND,
        "limitations": list(_FLOOR_LIMITATIONS),
    }
    if any(declaration.get(key) != value for key, value in expected.items()):
        _fail(
            "invalid_claim_reference",
            "Floor structural claim must use evaluator-owned canonical wording",
        )


def _normalize_patch_files(
    manifest: Mapping[str, Any],
    run_id: str,
    output: Mapping[str, Any],
) -> tuple[
    list[dict[str, Any]],
    list[dict[str, Any]],
    list[tuple[str, str, bytes]],
    list[tuple[str, str, bytes]],
]:
    patch_diff = output.get("patch_diff")
    original_files = output.get("original_files")
    files = output.get("patched_files")
    comparison_contract = manifest.get("comparison_contract")
    writable_paths = (
        comparison_contract.get("writable_paths")
        if isinstance(comparison_contract, Mapping)
        else None
    )
    if (
        not isinstance(patch_diff, str)
        or not patch_diff.strip()
        or not isinstance(original_files, list)
        or not isinstance(files, list)
        or not files
        or not isinstance(writable_paths, list)
    ):
        _fail("invalid_patch_result", "accepted patch must be non-empty and allowlisted")

    originals = _closed_file_content_map(
        original_files,
        writable_paths=writable_paths,
        label="original files",
    )
    patched = _closed_file_content_map(
        files,
        writable_paths=writable_paths,
        label="patched files",
    )
    if set(originals) != set(patched):
        _fail(
            "invalid_patch_result",
            "original and patched file path sets must match exactly",
        )
    expected_diff = _canonical_patch_diff(originals, patched)
    if not expected_diff or patch_diff != expected_diff:
        _fail(
            "invalid_patch_result",
            "patch diff must equal the evaluator-derived original/patched sidecar diff",
        )

    normalized_originals, original_payloads = _normalized_file_sidecars(
        run_id,
        originals,
        artifact_label="original_file",
    )
    normalized_patched, patched_payloads = _normalized_file_sidecars(
        run_id,
        patched,
        artifact_label="patched_file",
    )
    return (
        normalized_originals,
        normalized_patched,
        original_payloads,
        patched_payloads,
    )


def _normalized_file_sidecars(
    run_id: str,
    files: Mapping[str, str],
    *,
    artifact_label: str,
) -> tuple[list[dict[str, Any]], list[tuple[str, str, bytes]]]:
    normalized: list[dict[str, Any]] = []
    payloads: list[tuple[str, str, bytes]] = []
    for index, path in enumerate(files):
        content = files[path]
        try:
            content_bytes = content.encode("utf-8", errors="strict")
        except UnicodeEncodeError:
            _fail("invalid_patch_result", "file sidecar content must be UTF-8")
        normalized.append(
            {"path": path, "sha256": _sha256(content_bytes), "bytes": len(content_bytes)}
        )
        payloads.append((f"{run_id}_{artifact_label}_{index}", path, content_bytes))
    return normalized, payloads


def _closed_file_content_map(
    files: list[Any],
    *,
    writable_paths: list[Any],
    label: str,
) -> dict[str, str]:
    result: dict[str, str] = {}
    for file in files:
        if not isinstance(file, Mapping) or set(file) != {"path", "content"}:
            _fail(
                "invalid_patch_result",
                f"{label} must be closed path/content objects",
            )
        path = file.get("path")
        content = file.get("content")
        if (
            not isinstance(path, str)
            or path not in writable_paths
            or path in result
            or not isinstance(content, str)
        ):
            _fail(
                "invalid_patch_result",
                f"{label} path/content is invalid, duplicated, or out of allowlist",
            )
        result[path] = content
    return result


def _canonical_patch_diff(
    originals: Mapping[str, str],
    patched: Mapping[str, str],
) -> str:
    parts: list[str] = []
    for path in originals:
        parts.extend(
            difflib.unified_diff(
                originals[path].splitlines(keepends=True),
                patched[path].splitlines(keepends=True),
                fromfile=f"a/{path}",
                tofile=f"b/{path}",
                lineterm="\n",
            )
        )
    return "".join(parts)


def _floor_unscored_metrics(selected_sources: Any) -> dict[str, int]:
    if not isinstance(selected_sources, list):
        _fail("invalid_run_reference", "selected_sources must be a list")
    return {
        "stale_selected": 0,
        "selected_total": len(selected_sources),
        "required_selected": 0,
        "required_total": 0,
        "candidate_prior_selected": 0,
        "candidate_prior_total": 0,
    }


def _normalize_tests(value: Any, *, evidence_artifact_id: str) -> list[dict[str, Any]]:
    if not isinstance(value, list) or not value:
        _fail("invalid_test_result", "runner tests must be a non-empty list")
    normalized = []
    for item in value:
        if not isinstance(item, Mapping):
            _fail("invalid_test_result", "runner test entries must be objects")
        normalized.append(
            {
                "name": item.get("name"),
                "status": item.get("status"),
                "duration_ms": item.get("duration_ms"),
                "evidence_artifact_id": evidence_artifact_id,
            }
        )
    return normalized


def _provider_usage(provider_traces: list[Any]) -> dict[str, int]:
    input_tokens = 0
    output_tokens = 0
    total_tokens = 0
    for trace in provider_traces:
        if not isinstance(trace, Mapping) or not isinstance(
            trace.get("token_usage"), Mapping
        ):
            _fail("invalid_provider_trace", "provider trace usage is malformed")
        usage = trace["token_usage"]
        values = (
            usage.get("input_tokens"),
            usage.get("output_tokens"),
            usage.get("total_tokens"),
        )
        if any(not isinstance(value, int) or isinstance(value, bool) for value in values):
            _fail("invalid_provider_trace", "provider token usage must be integers")
        input_tokens += values[0]
        output_tokens += values[1]
        total_tokens += values[2]
    return {
        "provider_calls": len(provider_traces),
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "total_tokens": total_tokens,
    }


def _artifact_record(kind: str, path: str, payload: bytes) -> dict[str, Any]:
    return {
        "kind": kind,
        "relative_path": path,
        "sha256": _sha256(payload),
        "bytes": len(payload),
        "sanitized": True,
        "content_policy": "sanitized_bounded",
    }


def _copy_artifact_bytes(value: Mapping[str, bytes]) -> dict[str, bytes]:
    copied: dict[str, bytes] = {}
    for artifact_id, payload in value.items():
        if not isinstance(artifact_id, str) or not isinstance(payload, (bytes, bytearray)):
            _fail("invalid_artifact_reference", "artifact bytes must be a byte mapping")
        copied[artifact_id] = bytes(payload)
    return copied


def _merge_artifact_bytes(target: dict[str, bytes], source: Mapping[str, bytes]) -> None:
    for artifact_id, payload in source.items():
        if artifact_id in target and target[artifact_id] != payload:
            _fail("invalid_output_catalog", "output artifact ID collides")
        target[artifact_id] = bytes(payload)


def _text_bytes(value: Any, label: str) -> bytes:
    if not isinstance(value, str):
        _fail("invalid_output_catalog", f"{label} must be text")
    return value.encode("utf-8")


def _canonical_json_bytes(value: Any) -> bytes:
    try:
        return canonical_json(value).encode("utf-8")
    except (TypeError, ValueError) as exc:
        _fail("invalid_output_catalog", f"artifact is not canonical JSON: {type(exc).__name__}")


def _canonical_sha256(value: Any) -> str:
    return _sha256(_canonical_json_bytes(value))


def _sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _fail(code: str, detail: str) -> None:
    raise ValueError(f"4.0 {code} / {detail}")
