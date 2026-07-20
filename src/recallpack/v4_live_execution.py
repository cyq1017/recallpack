from __future__ import annotations

import base64
import binascii
import copy
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
import hashlib
from pathlib import Path, PurePosixPath
import tempfile
from typing import Any

from recallpack.downstream import (
    PatchGenerationProvider,
    PreparedDownstreamPatch,
    prepare_downstream_patch_result_from_contract,
)
from recallpack.budget import BudgetSelector, SelectedPack, count_canonical_json_tokens
from recallpack.compile import CompileRequest, CompileService
from recallpack.locking import ProjectTurnstileRegistry
from recallpack.observe import ObserveRequest, ObserveRuntime
from recallpack.providers import (
    ProviderError,
    ProviderMemoryDecider,
    ProviderRanker,
    ProviderTrace,
)
from recallpack.review_json import (
    canonicalize_review_json,
    parse_review_json,
    review_json_sha256,
)
from recallpack.review_seed_draft import build_deterministic_file_bundle
from recallpack.storage import SqliteEventStore
from recallpack.write_candidates import cosine_similarity, validated_query_vector, validated_vector


class FrozenLiveExecutionPlanError(ValueError):
    """Raised when a registered manifest cannot support a closed live run."""


_FROZEN_OUTPUT_FIXATION_MINT_AUTHORITY = object()


class _FrozenSelectionProviderFailure(FrozenLiveExecutionPlanError):
    """Internal provider failure that preserves only typed selection metadata."""

    def __init__(
        self,
        *,
        role: str,
        error: ProviderError,
        prior_traces: tuple[ProviderTrace, ...],
        provider_error_trace_retained: bool = False,
    ) -> None:
        if role not in {"embedding", "rerank"}:
            raise ValueError("invalid_selection_provider_role")
        self.role = role
        self.error = error
        self.prior_traces = prior_traces
        self.provider_error_trace_retained = provider_error_trace_retained
        super().__init__(f"selection_provider_failed: {error.code}")


class _FrozenSelectionRuntimeFailure(FrozenLiveExecutionPlanError):
    """Internal runtime response failure with the traces already produced."""

    def __init__(
        self,
        *,
        code: Any,
        prior_traces: tuple[ProviderTrace, ...],
    ) -> None:
        self.code = _safe_selection_failure_code(code)
        self.prior_traces = prior_traces
        super().__init__(f"selection_runtime_failed: {self.code}")


@dataclass(frozen=True)
class FrozenLiveExecutionCell:
    """One manifest-ordered live execution cell."""

    slot_id: str
    slot_index: int
    scenario_slot: str
    variant_id: str
    repetition: int
    planned_designation: str


@dataclass(frozen=True)
class FrozenRepositoryFile:
    """One content-verified file from a frozen repository bundle."""

    path: str
    content: bytes = field(repr=False)


@dataclass(frozen=True)
class FrozenScenarioEvent:
    """One model-visible event revalidated from a frozen fixture artifact."""

    source_ref: str
    observed_at: str
    actor: str
    kind: str
    summary: str


@dataclass(frozen=True)
class FrozenScenarioExecutionContract:
    """Task inputs deterministically derived from frozen scenario artifacts."""

    scenario_slot: str
    task_source_ref: str
    goal: str
    component: str
    allowed_edit_paths: tuple[str, ...]
    hidden_test_content_sha256: str
    repository_files: tuple[FrozenRepositoryFile, ...] = field(repr=False)
    events: tuple[FrozenScenarioEvent, ...] = field(repr=False)


@dataclass(frozen=True)
class FrozenLiveExecutionPlan:
    """Closed manifest-derived plan boundary for frozen live execution."""

    execution_manifest_sha256: str
    technical_failure_codes: tuple[str, ...]
    cells: tuple[FrozenLiveExecutionCell, ...]
    scenario_contracts: tuple[FrozenScenarioExecutionContract, ...]


@dataclass(frozen=True)
class FrozenExecutionProviders:
    """Injected provider factories; the frozen runtime never reads credentials."""

    embedding_provider_factory: Callable[[], Any] | None = None
    rerank_provider_factory: Callable[[], Any] | None = None
    memory_provider_factory: Callable[[], Any] | None = None
    patch_provider_factory: Callable[[], PatchGenerationProvider] | None = None


@dataclass(frozen=True)
class FrozenContextSelection:
    variant_id: str
    selected_context: tuple[dict[str, Any], ...]
    selected_source_refs: tuple[str, ...]
    model_visible_context: str
    model_visible_context_sha256: str
    exact_token_count: int
    budget_comparable: bool
    provider_traces: tuple[dict[str, Any], ...]
    execution_trace: dict[str, Any]


@dataclass(frozen=True)
class FrozenLiveCellResult:
    """One registered cell after context and patch preparation, before Docker."""

    cell: FrozenLiveExecutionCell
    execution_manifest_sha256: str
    attempt_no: int
    contract: FrozenScenarioExecutionContract
    selection: FrozenContextSelection
    downstream: dict[str, Any]
    generated_files: tuple[dict[str, str], ...]
    generated_files_sha256: str
    provider_traces: tuple[dict[str, Any], ...]
    attempt_outcome: dict[str, str]
    execution_trace: dict[str, Any]


@dataclass(frozen=True, init=False)
class FrozenOutputFixation:
    """Opaque custody binding for one pre-isolation model output.

    The constructor is intentionally private to this module. This is an
    in-process boundary, not a replacement for the evaluator's authenticated
    production receipt; it prevents an ordinary caller from supplying an
    unbound result to the production hidden-test path.
    """

    execution_manifest_sha256: str
    slot_id: str
    slot_index: int
    scenario_slot: str
    variant_id: str
    attempt_no: int
    model_output_sha256: str
    generated_files_sha256: str

    def __init__(
        self,
        *,
        execution_manifest_sha256: str,
        slot_id: str,
        slot_index: int,
        scenario_slot: str,
        variant_id: str,
        attempt_no: int,
        model_output_sha256: str,
        generated_files_sha256: str,
        _mint_authority: object,
    ) -> None:
        if _mint_authority is not _FROZEN_OUTPUT_FIXATION_MINT_AUTHORITY:
            raise TypeError("frozen output fixation cannot be constructed directly")
        object.__setattr__(self, "execution_manifest_sha256", execution_manifest_sha256)
        object.__setattr__(self, "slot_id", slot_id)
        object.__setattr__(self, "slot_index", slot_index)
        object.__setattr__(self, "scenario_slot", scenario_slot)
        object.__setattr__(self, "variant_id", variant_id)
        object.__setattr__(self, "attempt_no", attempt_no)
        object.__setattr__(self, "model_output_sha256", model_output_sha256)
        object.__setattr__(self, "generated_files_sha256", generated_files_sha256)


@dataclass(frozen=True)
class AuthorizedFrozenLiveCell:
    """A pre-isolation cell result with custody-confirmed output fixation."""

    result: FrozenLiveCellResult
    output_fixation: FrozenOutputFixation


class FrozenPreIsolationJournal:
    """Append-only ordering guard for patch preparation before hidden-test reveal.

    This is deliberately not a final evidence authority. It protects the
    manifest sequence while the executor has not yet handed an immutable patch
    to the evaluator-owned isolated runner and its production journal.
    """

    def __init__(self, plan: FrozenLiveExecutionPlan) -> None:
        if type(plan) is not FrozenLiveExecutionPlan:
            raise FrozenLiveExecutionPlanError("invalid_frozen_live_execution_plan")
        self._plan = plan
        self._results: list[FrozenLiveCellResult] = []

    @property
    def record_count(self) -> int:
        return len(self._results)

    def results(self) -> tuple[FrozenLiveCellResult, ...]:
        """Return an immutable snapshot so callers cannot mutate retained state."""
        return tuple(copy.deepcopy(self._results))

    def execute(
        self,
        *,
        slot_index: int,
        providers: FrozenExecutionProviders,
    ) -> FrozenLiveCellResult:
        expected_slot_index, expected_attempt_no = self._next_execution_position()
        if expected_slot_index >= len(self._plan.cells):
            raise FrozenLiveExecutionPlanError("all_execution_slots_already_prepared")
        if type(slot_index) is not int or slot_index != expected_slot_index:
            raise FrozenLiveExecutionPlanError(
                f"expected_execution_slot_index: {expected_slot_index}"
            )
        result = execute_frozen_live_cell(
            self._plan,
            slot_index=slot_index,
            providers=providers,
            attempt_no=expected_attempt_no,
        )
        self._results.append(result)
        return copy.deepcopy(result)

    def execute_authorized(
        self,
        *,
        slot_index: int,
        providers: FrozenExecutionProviders,
        authority: Any,
    ) -> AuthorizedFrozenLiveCell:
        """Run the next registered cell through custody authorization.

        Production callers use this method rather than ``execute`` so the
        append-only order guard and output fixation are one operation.
        """
        expected_slot_index, expected_attempt_no = self._next_execution_position()
        if expected_slot_index >= len(self._plan.cells):
            raise FrozenLiveExecutionPlanError("all_execution_slots_already_prepared")
        if type(slot_index) is not int or slot_index != expected_slot_index:
            raise FrozenLiveExecutionPlanError(
                f"expected_execution_slot_index: {expected_slot_index}"
            )
        authorized = execute_authorized_frozen_live_cell(
            self._plan,
            slot_index=slot_index,
            providers=providers,
            authority=authority,
            attempt_no=expected_attempt_no,
        )
        self._results.append(authorized.result)
        return AuthorizedFrozenLiveCell(
            result=copy.deepcopy(authorized.result),
            output_fixation=authorized.output_fixation,
        )

    def _next_execution_position(self) -> tuple[int, int]:
        if not self._results:
            first = self._plan.cells[0]
            return first.slot_index, first.repetition
        last = self._results[-1]
        if last.attempt_outcome.get("status") == "invalidated":
            return last.cell.slot_index, last.attempt_no + 1
        next_slot_index = last.cell.slot_index + 1
        if next_slot_index >= len(self._plan.cells):
            return next_slot_index, 0
        next_cell = self._plan.cells[next_slot_index]
        return next_cell.slot_index, next_cell.repetition


def serialize_frozen_pre_isolation_record(
    result: FrozenLiveCellResult,
) -> dict[str, Any]:
    """Produce the only shareable record for an unexecuted frozen cell.

    Patch bytes, source files, model-visible context, source references, hidden
    test content, and provider request identifiers remain inside the ephemeral
    execution result. The serialized envelope is intentionally small enough to
    be checked before any future evidence write or external disclosure.
    """
    if type(result) is not FrozenLiveCellResult:
        raise FrozenLiveExecutionPlanError("invalid_frozen_live_cell_result")
    cell = result.cell
    selection = result.selection
    if (
        type(cell) is not FrozenLiveExecutionCell
        or type(selection) is not FrozenContextSelection
        or not _is_sha256(result.execution_manifest_sha256)
        or result.execution_trace.get("execution_manifest_sha256")
        != result.execution_manifest_sha256
    ):
        raise FrozenLiveExecutionPlanError("invalid_pre_isolation_execution_record")
    execution_manifest_sha256 = result.execution_manifest_sha256
    if (
        not _safe_public_identifier(cell.slot_id)
        or type(cell.slot_index) is not int
        or cell.slot_index < 0
        or not _safe_public_identifier(cell.scenario_slot)
        or not _safe_public_identifier(cell.variant_id)
        or type(cell.repetition) is not int
        or cell.repetition < 1
        or cell.planned_designation not in {"headline", "diagnostic"}
        or type(result.attempt_no) is not int
        or result.attempt_no < cell.repetition
        or not _is_sha256(selection.model_visible_context_sha256)
        or type(selection.exact_token_count) is not int
        or selection.exact_token_count < 0
        or type(selection.budget_comparable) is not bool
    ):
        raise FrozenLiveExecutionPlanError("invalid_pre_isolation_execution_record")
    return {
        "record_type": "frozen_pre_isolation_attempt/v1",
        "execution": {
            "execution_manifest_sha256": execution_manifest_sha256,
            "slot_id": cell.slot_id,
            "slot_index": cell.slot_index,
            "attempt_no": result.attempt_no,
            "scenario_slot": cell.scenario_slot,
            "variant_id": cell.variant_id,
            "repetition": cell.repetition,
            "planned_designation": cell.planned_designation,
        },
        "selected_context": {
            "model_visible_context_sha256": selection.model_visible_context_sha256,
            "exact_token_count": selection.exact_token_count,
            "budget_comparable": selection.budget_comparable,
        },
        "provider_traces": [
            _sanitize_frozen_provider_trace(trace)
            for trace in result.provider_traces
        ],
        "downstream": _sanitize_frozen_downstream(result),
        "attempt_outcome": _sanitize_attempt_outcome(result.attempt_outcome),
    }


def _sanitize_frozen_provider_trace(trace: Any) -> dict[str, Any]:
    expected_fields = {
        "role",
        "provider_family",
        "model_name",
        "request_purpose",
        "input_item_count",
        "input_token_estimate",
        "output_item_count",
        "latency_ms",
        "live",
        "deterministic_fallback",
        "request_id_present",
        "token_usage",
    }
    if not isinstance(trace, Mapping) or set(trace) != expected_fields:
        raise FrozenLiveExecutionPlanError("unsafe_provider_trace_metadata")
    role = trace.get("role")
    provider_family = trace.get("provider_family")
    model_name = trace.get("model_name")
    request_purpose = trace.get("request_purpose")
    if (
        role not in {"memory_decision", "embedding", "rerank", "patch_generation"}
        or provider_family
        not in {"qwen_cloud", "deterministic_fake", "invalid_provider_output"}
        or not _safe_public_identifier(model_name)
        or not _safe_public_identifier(request_purpose)
        or any(
            type(trace.get(field)) is not int or trace[field] < 0
            for field in (
                "input_item_count",
                "input_token_estimate",
                "output_item_count",
                "latency_ms",
            )
        )
        or any(
            type(trace.get(field)) is not bool
            for field in ("live", "deterministic_fallback", "request_id_present")
        )
    ):
        raise FrozenLiveExecutionPlanError("unsafe_provider_trace_metadata")
    usage = trace.get("token_usage")
    expected_usage_fields = {
        "input_tokens",
        "output_tokens",
        "total_tokens",
        "reported_by_provider",
    }
    if (
        not isinstance(usage, Mapping)
        or set(usage) != expected_usage_fields
        or any(
            type(usage.get(field)) is not int or usage[field] < 0
            for field in ("input_tokens", "output_tokens", "total_tokens")
        )
        or type(usage.get("reported_by_provider")) is not bool
    ):
        raise FrozenLiveExecutionPlanError("unsafe_provider_trace_metadata")
    return {
        "role": role,
        "provider_family": provider_family,
        "model_name": model_name,
        "request_purpose": request_purpose,
        "input_item_count": trace["input_item_count"],
        "input_token_estimate": trace["input_token_estimate"],
        "output_item_count": trace["output_item_count"],
        "latency_ms": trace["latency_ms"],
        "live": trace["live"],
        "deterministic_fallback": trace["deterministic_fallback"],
        "request_id_present": trace["request_id_present"],
        "token_usage": dict(usage),
    }


def _sanitize_frozen_downstream(result: FrozenLiveCellResult) -> dict[str, Any]:
    downstream = result.downstream
    if not isinstance(downstream, Mapping) or type(downstream.get("accepted")) is not bool:
        raise FrozenLiveExecutionPlanError("invalid_pre_isolation_downstream_result")
    patch_diff = downstream.get("patch_diff")
    test_status = downstream.get("test_status")
    patch_generation = downstream.get("patch_generation")
    if (
        not isinstance(patch_diff, str)
        or not _safe_public_identifier(test_status)
        or not isinstance(patch_generation, Mapping)
        or type(patch_generation.get("used_gold_patch_variants")) is not bool
        or not isinstance(patch_generation.get("output_paths"), list)
    ):
        raise FrozenLiveExecutionPlanError("invalid_pre_isolation_downstream_result")
    output_paths = tuple(
        _canonical_repository_path(path) for path in patch_generation["output_paths"]
    )
    generated_paths = tuple(
        _canonical_repository_path(item.get("path"))
        if isinstance(item, Mapping)
        else ""
        for item in result.generated_files
    )
    if (
        len(output_paths) != len(set(output_paths))
        or output_paths != generated_paths
        or not _is_sha256(result.generated_files_sha256)
        or result.generated_files_sha256
        != _frozen_generated_files_sha256(result.generated_files)
    ):
        raise FrozenLiveExecutionPlanError("invalid_pre_isolation_downstream_result")
    error = downstream.get("error")
    if error is not None and not _safe_public_identifier(error):
        raise FrozenLiveExecutionPlanError("invalid_pre_isolation_downstream_result")
    isolated_evaluation = result.execution_trace.get("isolated_evaluation")
    if isolated_evaluation != "not_run":
        raise FrozenLiveExecutionPlanError("invalid_pre_isolation_downstream_result")
    return {
        "accepted": downstream["accepted"],
        "error_code": error,
        "generated_patch_sha256": result.generated_files_sha256,
        "patch_output_paths": list(output_paths),
        "test_status": test_status,
        "isolated_evaluation": isolated_evaluation,
        "used_gold_patch_variants": patch_generation["used_gold_patch_variants"],
    }


def _sanitize_attempt_outcome(value: Any) -> dict[str, str]:
    expected_fields = {"status", "stage", "code"}
    if (
        not isinstance(value, Mapping)
        or set(value) != expected_fields
        or any(not _safe_public_identifier(value.get(field)) for field in expected_fields)
    ):
        raise FrozenLiveExecutionPlanError("invalid_pre_isolation_attempt_outcome")
    return {field: value[field] for field in sorted(expected_fields)}


def _safe_public_identifier(value: Any) -> bool:
    if (
        not isinstance(value, str)
        or not value
        or len(value) > 160
        or not value.isascii()
        or any(character not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._-/" for character in value)
    ):
        return False
    normalized = value.casefold()
    return not any(
        marker in normalized
        for marker in (
            "sk-",
            "api_key",
            "apikey",
            "authorization",
            "bearer",
            "secret",
            "credential",
            "private",
            "/users/",
            "/home/",
        )
    )


def build_frozen_live_execution_plan(
    manifest: Mapping[str, Any],
    *,
    artifact_bytes: Mapping[str, bytes],
) -> FrozenLiveExecutionPlan:
    """Build a closed plan from manifest-declared artifact bytes only.

    The task goal, component, and allowlist are derived from frozen inputs. No
    filesystem path or caller-provided task metadata is accepted here, which
    prevents an evidence run from silently falling back to local `gold.json`.
    """
    catalog = manifest.get("input_artifact_catalog")
    if not isinstance(catalog, Mapping):
        raise FrozenLiveExecutionPlanError("invalid_input_artifact_catalog")
    scenarios = manifest.get("evidence_scenarios")
    if not isinstance(scenarios, list):
        raise FrozenLiveExecutionPlanError("invalid_evidence_scenarios")
    writable_paths = _frozen_writable_paths(manifest)
    hidden_test_hashes = manifest.get("hidden_test_hashes")
    if not isinstance(hidden_test_hashes, Mapping):
        raise FrozenLiveExecutionPlanError("invalid_hidden_test_hashes")
    scenario_contracts: list[FrozenScenarioExecutionContract] = []
    scenario_slots: set[str] = set()
    for scenario in scenarios:
        if not isinstance(scenario, Mapping):
            raise FrozenLiveExecutionPlanError("invalid_evidence_scenario")
        slot = scenario.get("scenario_slot")
        if not isinstance(slot, str) or not slot or slot in scenario_slots:
            raise FrozenLiveExecutionPlanError("invalid_scenario_slot")
        scenario_slots.add(slot)
        scenario_contracts.append(
            _derive_scenario_contract(
                scenario,
                catalog=catalog,
                artifact_bytes=artifact_bytes,
                writable_paths=writable_paths,
                hidden_test_hashes=hidden_test_hashes,
            )
        )

    execution_order = manifest.get("execution_order")
    if not isinstance(execution_order, list):
        raise FrozenLiveExecutionPlanError("invalid_execution_order")
    variants = manifest.get("variants")
    if (
        not isinstance(variants, list)
        or not variants
        or not all(isinstance(variant, str) and variant for variant in variants)
    ):
        raise FrozenLiveExecutionPlanError("invalid_variants")
    known_variants = set(variants)
    technical_failure_codes = _frozen_technical_failure_codes(manifest)
    seen_slot_ids: set[str] = set()
    cells: list[FrozenLiveExecutionCell] = []
    for expected_index, raw_cell in enumerate(execution_order):
        if not isinstance(raw_cell, Mapping):
            raise FrozenLiveExecutionPlanError("invalid_execution_cell")
        slot_id = raw_cell.get("slot_id")
        slot_index = raw_cell.get("slot_index")
        scenario_slot = raw_cell.get("scenario_slot")
        variant_id = raw_cell.get("variant_id")
        repetition = raw_cell.get("repetition")
        planned_designation = raw_cell.get("planned_designation")
        if (
            not isinstance(slot_id, str)
            or not slot_id
            or slot_id in seen_slot_ids
            or type(slot_index) is not int
            or slot_index != expected_index
            or scenario_slot not in scenario_slots
            or variant_id not in known_variants
            or type(repetition) is not int
            or repetition < 1
            or planned_designation not in {"headline", "diagnostic"}
        ):
            raise FrozenLiveExecutionPlanError("invalid_execution_cell")
        seen_slot_ids.add(slot_id)
        cells.append(
            FrozenLiveExecutionCell(
                slot_id=slot_id,
                slot_index=slot_index,
                scenario_slot=scenario_slot,
                variant_id=variant_id,
                repetition=repetition,
                planned_designation=planned_designation,
            )
        )
    return FrozenLiveExecutionPlan(
        execution_manifest_sha256=review_json_sha256(manifest),
        technical_failure_codes=technical_failure_codes,
        cells=tuple(cells),
        scenario_contracts=tuple(scenario_contracts),
    )


def _frozen_technical_failure_codes(manifest: Mapping[str, Any]) -> tuple[str, ...]:
    raw_codes = manifest.get("technical_failure_codes")
    if (
        not isinstance(raw_codes, list)
        or not raw_codes
        or any(not _safe_public_identifier(code) for code in raw_codes)
        or len(raw_codes) != len(set(raw_codes))
    ):
        raise FrozenLiveExecutionPlanError("invalid_technical_failure_codes")
    return tuple(raw_codes)


def _frozen_writable_paths(manifest: Mapping[str, Any]) -> tuple[str, ...]:
    comparison = manifest.get("comparison_contract")
    if not isinstance(comparison, Mapping):
        raise FrozenLiveExecutionPlanError("invalid_comparison_contract")
    raw_paths = comparison.get("writable_paths")
    if not isinstance(raw_paths, list) or not raw_paths:
        raise FrozenLiveExecutionPlanError("invalid_frozen_writable_paths")
    paths = tuple(sorted({_canonical_repository_path(path) for path in raw_paths}))
    if len(paths) != len(raw_paths):
        raise FrozenLiveExecutionPlanError("invalid_frozen_writable_paths")
    return paths


def _derive_scenario_contract(
    scenario: Mapping[str, Any],
    *,
    catalog: Mapping[str, Any],
    artifact_bytes: Mapping[str, bytes],
    writable_paths: tuple[str, ...],
    hidden_test_hashes: Mapping[str, Any],
) -> FrozenScenarioExecutionContract:
    slot = scenario.get("scenario_slot")
    if not isinstance(slot, str) or not slot:
        raise FrozenLiveExecutionPlanError("invalid_scenario_slot")
    fixture = _load_json_artifact(
        scenario,
        field="fixture_artifact_id",
        expected_kind="fixture",
        catalog=catalog,
        artifact_bytes=artifact_bytes,
    )
    repository_bundle = _load_json_artifact(
        scenario,
        field="repository_snapshot_artifact_id",
        expected_kind="repository_snapshot",
        catalog=catalog,
        artifact_bytes=artifact_bytes,
    )
    hidden_hash = _load_frozen_artifact(
        scenario,
        field="hidden_test_hash_artifact_id",
        expected_kind="hidden_test_hash",
        catalog=catalog,
        artifact_bytes=artifact_bytes,
    )
    hidden_test_content_sha256 = hidden_test_hashes.get(slot)
    if not _is_sha256(hidden_test_content_sha256):
        raise FrozenLiveExecutionPlanError(f"invalid_hidden_test_hash: {slot}")
    if hidden_hash != hidden_test_content_sha256.encode("ascii"):
        raise FrozenLiveExecutionPlanError(f"hidden_test_hash_mismatch: {slot}")

    events = _frozen_fixture_events(fixture, slot)
    task_source_ref, goal = _handoff_goal(events, slot)
    repository_files = _repository_bundle_files(repository_bundle, slot)
    repository_paths = {item.path for item in repository_files}
    allowed_edit_paths = tuple(path for path in writable_paths if path in repository_paths)
    if not allowed_edit_paths:
        raise FrozenLiveExecutionPlanError(f"missing_scenario_writable_paths: {slot}")
    source_paths = [
        path
        for path in allowed_edit_paths
        if len(PurePosixPath(path).parts) == 2
        and path.startswith("src/")
        and path.endswith(".py")
    ]
    if len(source_paths) != 1:
        raise FrozenLiveExecutionPlanError(
            f"ambiguous_or_missing_component: {slot}"
        )
    component = PurePosixPath(source_paths[0]).stem
    if not component:
        raise FrozenLiveExecutionPlanError(f"ambiguous_or_missing_component: {slot}")
    return FrozenScenarioExecutionContract(
        scenario_slot=slot,
        task_source_ref=task_source_ref,
        goal=goal,
        component=component,
        allowed_edit_paths=allowed_edit_paths,
        hidden_test_content_sha256=hidden_test_content_sha256,
        repository_files=repository_files,
        events=events,
    )


def _load_json_artifact(
    scenario: Mapping[str, Any],
    *,
    field: str,
    expected_kind: str,
    catalog: Mapping[str, Any],
    artifact_bytes: Mapping[str, bytes],
) -> Mapping[str, Any]:
    payload = _load_frozen_artifact(
        scenario,
        field=field,
        expected_kind=expected_kind,
        catalog=catalog,
        artifact_bytes=artifact_bytes,
    )
    try:
        value = parse_review_json(payload)
    except ValueError as exc:
        raise FrozenLiveExecutionPlanError(
            f"invalid_frozen_json_artifact: {field}"
        ) from exc
    if not isinstance(value, Mapping):
        raise FrozenLiveExecutionPlanError(f"invalid_frozen_json_artifact: {field}")
    return value


def _load_frozen_artifact(
    scenario: Mapping[str, Any],
    *,
    field: str,
    expected_kind: str,
    catalog: Mapping[str, Any],
    artifact_bytes: Mapping[str, bytes],
) -> bytes:
    artifact_id = scenario.get(field)
    if not isinstance(artifact_id, str) or not artifact_id:
        raise FrozenLiveExecutionPlanError(f"missing_frozen_artifact_id: {field}")
    record = catalog.get(artifact_id)
    if not isinstance(record, Mapping) or record.get("kind") != expected_kind:
        raise FrozenLiveExecutionPlanError(f"invalid_frozen_artifact: {artifact_id}")
    payload = artifact_bytes.get(artifact_id)
    if not isinstance(payload, bytes):
        raise FrozenLiveExecutionPlanError(f"missing_frozen_artifact_bytes: {artifact_id}")
    expected_size = record.get("bytes")
    expected_sha256 = record.get("sha256")
    if (
        type(expected_size) is not int
        or expected_size != len(payload)
        or not _is_sha256(expected_sha256)
        or hashlib.sha256(payload).hexdigest() != expected_sha256
    ):
        raise FrozenLiveExecutionPlanError(f"frozen_artifact_digest_mismatch: {artifact_id}")
    return payload


def _frozen_fixture_events(
    fixture: Mapping[str, Any],
    slot: str,
) -> tuple[FrozenScenarioEvent, ...]:
    if (
        fixture.get("record_type") != "fixture"
        or fixture.get("scenario_slot") != slot
        or not isinstance(fixture.get("events"), list)
        or not fixture["events"]
    ):
        raise FrozenLiveExecutionPlanError(f"invalid_frozen_fixture: {slot}")
    events: list[FrozenScenarioEvent] = []
    source_refs: set[str] = set()
    expected_fields = {
        "source_ref",
        "observed_at",
        "actor",
        "kind",
        "summary",
        "model_visible",
        "authored_summary",
    }
    for event in fixture["events"]:
        if (
            not isinstance(event, Mapping)
            or set(event) != expected_fields
            or not isinstance(event.get("source_ref"), str)
            or not event["source_ref"]
            or event["source_ref"] in source_refs
            or not isinstance(event.get("observed_at"), str)
            or not event["observed_at"]
            or event.get("actor") not in {"user", "assistant", "tool"}
            or event.get("kind") not in {"message", "test_result", "command_result"}
            or not isinstance(event.get("summary"), str)
            or not event["summary"]
            or event.get("model_visible") is not True
            or event.get("authored_summary") is not True
        ):
            raise FrozenLiveExecutionPlanError(f"invalid_frozen_fixture: {slot}")
        source_refs.add(event["source_ref"])
        events.append(
            FrozenScenarioEvent(
                source_ref=event["source_ref"],
                observed_at=event["observed_at"],
                actor=event["actor"],
                kind=event["kind"],
                summary=event["summary"],
            )
        )
    return tuple(events)


def _handoff_goal(
    events: tuple[FrozenScenarioEvent, ...],
    slot: str,
) -> tuple[str, str]:
    final_event = events[-1]
    if (
        final_event.kind != "message"
        or "handoff task" not in final_event.summary.lower()
    ):
        raise FrozenLiveExecutionPlanError(f"invalid_frozen_handoff_task: {slot}")
    return final_event.source_ref, final_event.summary


def materialize_frozen_repository(
    contract: FrozenScenarioExecutionContract,
    destination: str | Path,
) -> Path:
    """Create a temporary repository solely from the contract's frozen files."""
    if type(contract) is not FrozenScenarioExecutionContract:
        raise FrozenLiveExecutionPlanError("invalid_frozen_scenario_contract")
    root = Path(destination)
    if root.exists() or root.is_symlink():
        raise FrozenLiveExecutionPlanError("repository_materialization_target_exists")
    root.mkdir(parents=True, exist_ok=False)
    for frozen_file in contract.repository_files:
        relative = _canonical_repository_path(frozen_file.path)
        target = root.joinpath(*PurePosixPath(relative).parts)
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("xb") as handle:
            handle.write(frozen_file.content)
        if target.read_bytes() != frozen_file.content:
            raise FrozenLiveExecutionPlanError("repository_materialization_mismatch")
    return root.resolve(strict=True)


def verify_frozen_hidden_test_root(
    contract: FrozenScenarioExecutionContract,
    hidden_test_root: str | Path,
) -> str:
    """Verify the opaque local hidden-test tree before isolated execution."""
    if type(contract) is not FrozenScenarioExecutionContract:
        raise FrozenLiveExecutionPlanError("invalid_frozen_scenario_contract")
    try:
        bundle = build_deterministic_file_bundle(
            Path(hidden_test_root),
            scenario_slot=contract.scenario_slot,
            purpose="hidden_tests",
        )
    except (OSError, ValueError) as exc:
        raise FrozenLiveExecutionPlanError("hidden_test_root_unavailable") from exc
    actual_hash = hashlib.sha256(canonicalize_review_json(bundle)).hexdigest()
    if actual_hash != contract.hidden_test_content_sha256:
        raise FrozenLiveExecutionPlanError(
            f"hidden_test_root_hash_mismatch: {contract.scenario_slot}"
        )
    return actual_hash


def prepare_frozen_downstream_patch(
    contract: FrozenScenarioExecutionContract,
    *,
    selected_context: list[dict[str, Any]],
    variant_id: str,
    patch_provider: PatchGenerationProvider | None = None,
) -> dict[str, Any]:
    """Generate a patch from a frozen task contract without fixture metadata."""
    return prepare_frozen_downstream_patch_result(
        contract,
        selected_context=selected_context,
        variant_id=variant_id,
        patch_provider=patch_provider,
    ).payload


def prepare_frozen_downstream_patch_result(
    contract: FrozenScenarioExecutionContract,
    *,
    selected_context: list[dict[str, Any]],
    variant_id: str,
    patch_provider: PatchGenerationProvider | None = None,
) -> PreparedDownstreamPatch:
    """Prepare a frozen patch while retaining its typed trace for the executor."""
    if type(contract) is not FrozenScenarioExecutionContract:
        raise FrozenLiveExecutionPlanError("invalid_frozen_scenario_contract")
    if not isinstance(selected_context, list) or not all(
        isinstance(item, dict) for item in selected_context
    ):
        raise FrozenLiveExecutionPlanError("invalid_selected_context")
    if not isinstance(variant_id, str) or not variant_id:
        raise FrozenLiveExecutionPlanError("invalid_variant_id")
    with tempfile.TemporaryDirectory(prefix="recallpack-v4-frozen-patch-") as temporary:
        repository_root = materialize_frozen_repository(
            contract,
            Path(temporary) / "repository",
        )
        return prepare_downstream_patch_result_from_contract(
            repository_root=repository_root,
            goal=contract.goal,
            allowed_paths=list(contract.allowed_edit_paths),
            selected_context=selected_context,
            variant_id=variant_id,
            patch_provider=patch_provider,
        )


def execute_frozen_live_cell(
    plan: FrozenLiveExecutionPlan,
    *,
    slot_index: int,
    providers: FrozenExecutionProviders,
    attempt_no: int | None = None,
) -> FrozenLiveCellResult:
    """Execute one manifest-registered cell through patch preparation only.

    This primitive intentionally does not mount hidden tests or start Docker.
    The returned attempt remains incomplete until a separate isolated evaluator
    produces an authenticated execution receipt.
    """
    if type(plan) is not FrozenLiveExecutionPlan:
        raise FrozenLiveExecutionPlanError("invalid_frozen_live_execution_plan")
    if type(slot_index) is not int or slot_index < 0:
        raise FrozenLiveExecutionPlanError("invalid_execution_slot_index")
    if type(providers) is not FrozenExecutionProviders:
        raise FrozenLiveExecutionPlanError("invalid_execution_providers")
    if slot_index >= len(plan.cells):
        raise FrozenLiveExecutionPlanError("unknown_execution_slot_index")
    cell = plan.cells[slot_index]
    if cell.slot_index != slot_index:
        raise FrozenLiveExecutionPlanError("invalid_execution_slot_index")
    contract = next(
        (
            item
            for item in plan.scenario_contracts
            if item.scenario_slot == cell.scenario_slot
        ),
        None,
    )
    if contract is None:
        raise FrozenLiveExecutionPlanError("execution_cell_contract_missing")
    resolved_attempt_no = cell.repetition if attempt_no is None else attempt_no
    if (
        type(resolved_attempt_no) is not int
        or resolved_attempt_no < cell.repetition
    ):
        raise FrozenLiveExecutionPlanError("invalid_execution_attempt_no")

    try:
        selection = select_frozen_context(
            contract,
            variant_id=cell.variant_id,
            providers=providers,
        )
    except _FrozenSelectionProviderFailure as exc:
        return _selection_failure_result(
            plan=plan,
            cell=cell,
            contract=contract,
            attempt_no=resolved_attempt_no,
            code=exc.error.code,
            retryable=exc.error.retryable,
            provider_role=exc.role,
            provider_error=exc.error,
            prior_traces=exc.prior_traces,
            provider_error_trace_retained=exc.provider_error_trace_retained,
        )
    except ProviderError as exc:
        return _selection_failure_result(
            plan=plan,
            cell=cell,
            contract=contract,
            attempt_no=resolved_attempt_no,
            code=exc.code,
            retryable=exc.retryable,
            provider_role=None,
            provider_error=None,
            prior_traces=(),
            provider_error_trace_retained=False,
        )
    except _FrozenSelectionRuntimeFailure as exc:
        return _selection_failure_result(
            plan=plan,
            cell=cell,
            contract=contract,
            attempt_no=resolved_attempt_no,
            code=exc.code,
            retryable=_retryable_frozen_failure_code(exc.code, plan),
            provider_role=None,
            provider_error=None,
            prior_traces=exc.prior_traces,
            provider_error_trace_retained=False,
        )
    except FrozenLiveExecutionPlanError as exc:
        failure_code = _frozen_selection_runtime_failure_code(exc, plan)
        if failure_code is None:
            raise
        return _selection_failure_result(
            plan=plan,
            cell=cell,
            contract=contract,
            attempt_no=resolved_attempt_no,
            code=failure_code,
            retryable=_retryable_frozen_failure_code(failure_code, plan),
            provider_role=None,
            provider_error=None,
            prior_traces=(),
            provider_error_trace_retained=False,
        )
    prepared = prepare_frozen_downstream_patch_result(
        contract,
        selected_context=[dict(item) for item in selection.selected_context],
        variant_id=cell.variant_id,
        patch_provider=_required_provider(
            providers.patch_provider_factory,
            "patch_provider_factory",
        ),
    )
    patch_trace = _patch_trace_record(
        prepared,
        selected_context_count=len(selection.selected_context),
    )
    accepted = prepared.payload.get("accepted") is True
    error = prepared.payload.get("error")
    technical_failure = (
        prepared.provider_failure_retryable
        and prepared.provider_failure_code in plan.technical_failure_codes
    )
    attempt_outcome = (
        {
            "status": "incomplete",
            "stage": "isolated_evaluation",
            "code": "not_run",
        }
        if accepted
        else {
            "status": "invalidated",
            "stage": "patch_generation",
            "code": prepared.provider_failure_code,
        }
        if technical_failure
        else {
            "status": "adverse",
            "stage": "patch_generation",
            "code": error if isinstance(error, str) and error else "patch_rejected",
        }
    )
    execution_trace = {
        "execution_manifest_sha256": plan.execution_manifest_sha256,
        "slot_id": cell.slot_id,
        "slot_index": cell.slot_index,
        "attempt_no": resolved_attempt_no,
        "scenario_slot": cell.scenario_slot,
        "variant_id": cell.variant_id,
        "repetition": cell.repetition,
        "selection": dict(selection.execution_trace),
        "selected_context_sha256": selection.model_visible_context_sha256,
        "selected_context_token_count": selection.exact_token_count,
        "patch_generation_accepted": accepted,
        "isolated_evaluation": "not_run",
    }
    return FrozenLiveCellResult(
        cell=cell,
        execution_manifest_sha256=plan.execution_manifest_sha256,
        attempt_no=resolved_attempt_no,
        contract=contract,
        selection=selection,
        downstream=dict(prepared.payload),
        generated_files=prepared.generated_files,
        generated_files_sha256=_frozen_generated_files_sha256(prepared.generated_files),
        provider_traces=(*selection.provider_traces, patch_trace),
        attempt_outcome=attempt_outcome,
        execution_trace=execution_trace,
    )


def execute_authorized_frozen_live_cell(
    plan: FrozenLiveExecutionPlan,
    *,
    slot_index: int,
    providers: FrozenExecutionProviders,
    authority: Any,
    attempt_no: int | None = None,
) -> AuthorizedFrozenLiveCell:
    """Authorize provider work, then fix its output before hidden-test access.

    Callers using ``RevealAuthority`` must prepare the registered attempt and
    complete its required pre-output reveals before entering this function. The
    executor deliberately receives no extraction root and no hidden-test path.
    """
    cell, resolved_attempt_no = _authorized_execution_position(
        plan,
        slot_index=slot_index,
        providers=providers,
        attempt_no=attempt_no,
    )
    _validate_frozen_execution_authority(authority)
    _authorize_frozen_provider_action(authority, cell, resolved_attempt_no)
    result = execute_frozen_live_cell(
        plan,
        slot_index=slot_index,
        providers=providers,
        attempt_no=resolved_attempt_no,
    )
    output_sha256 = frozen_model_output_sha256(result)
    _fix_frozen_model_output(
        authority,
        cell,
        resolved_attempt_no,
        output_sha256=output_sha256,
        patch_sha256=result.generated_files_sha256,
    )
    return AuthorizedFrozenLiveCell(
        result=result,
        output_fixation=_mint_frozen_output_fixation(result, output_sha256),
    )


def frozen_model_output_sha256(result: FrozenLiveCellResult) -> str:
    """Hash the closed pre-isolation outcome without disclosing its contents."""
    record = serialize_frozen_pre_isolation_record(result)
    try:
        record_sha256 = hashlib.sha256(canonicalize_review_json(record)).hexdigest()
        execution_trace_sha256 = hashlib.sha256(
            canonicalize_review_json(result.execution_trace)
        ).hexdigest()
        return hashlib.sha256(
            canonicalize_review_json(
                {
                    "record_type": "frozen_model_output_binding/v1",
                    "pre_isolation_record_sha256": record_sha256,
                    "execution_trace_sha256": execution_trace_sha256,
                }
            )
        ).hexdigest()
    except (TypeError, ValueError) as exc:
        raise FrozenLiveExecutionPlanError("invalid_frozen_model_output") from exc


def _authorized_execution_position(
    plan: FrozenLiveExecutionPlan,
    *,
    slot_index: int,
    providers: FrozenExecutionProviders,
    attempt_no: int | None,
) -> tuple[FrozenLiveExecutionCell, int]:
    """Validate only deterministic cell identity before provider authorization."""
    if type(plan) is not FrozenLiveExecutionPlan:
        raise FrozenLiveExecutionPlanError("invalid_frozen_live_execution_plan")
    if type(providers) is not FrozenExecutionProviders:
        raise FrozenLiveExecutionPlanError("invalid_execution_providers")
    if type(slot_index) is not int or slot_index < 0:
        raise FrozenLiveExecutionPlanError("invalid_execution_slot_index")
    if slot_index >= len(plan.cells):
        raise FrozenLiveExecutionPlanError("unknown_execution_slot_index")
    cell = plan.cells[slot_index]
    if cell.slot_index != slot_index:
        raise FrozenLiveExecutionPlanError("invalid_execution_slot_index")
    resolved_attempt_no = cell.repetition if attempt_no is None else attempt_no
    if type(resolved_attempt_no) is not int or resolved_attempt_no < cell.repetition:
        raise FrozenLiveExecutionPlanError("invalid_execution_attempt_no")
    return cell, resolved_attempt_no


def _authorize_frozen_provider_action(
    authority: Any,
    cell: FrozenLiveExecutionCell,
    attempt_no: int,
) -> None:
    authorize = authority.authorize_provider_action
    authorize(cell.slot_id, attempt_no, extraction_root=None)


def _fix_frozen_model_output(
    authority: Any,
    cell: FrozenLiveExecutionCell,
    attempt_no: int,
    *,
    output_sha256: str,
    patch_sha256: str,
) -> None:
    fix = authority.fix_model_output
    fix(
        cell.slot_id,
        attempt_no,
        output_sha256=output_sha256,
        patch_sha256=patch_sha256,
    )


def _validate_frozen_execution_authority(authority: Any) -> None:
    if not (
        callable(getattr(authority, "authorize_provider_action", None))
        and callable(getattr(authority, "fix_model_output", None))
    ):
        raise FrozenLiveExecutionPlanError("invalid_frozen_execution_authority")


def _mint_frozen_output_fixation(
    result: FrozenLiveCellResult,
    output_sha256: str,
) -> FrozenOutputFixation:
    return FrozenOutputFixation(
        execution_manifest_sha256=result.execution_manifest_sha256,
        slot_id=result.cell.slot_id,
        slot_index=result.cell.slot_index,
        scenario_slot=result.contract.scenario_slot,
        variant_id=result.cell.variant_id,
        attempt_no=result.attempt_no,
        model_output_sha256=output_sha256,
        generated_files_sha256=result.generated_files_sha256,
        _mint_authority=_FROZEN_OUTPUT_FIXATION_MINT_AUTHORITY,
    )


def build_frozen_production_execution_identity(
    result: FrozenLiveCellResult,
) -> Any:
    """Derive the production identity from the frozen repository contract.

    This helper reads only the frozen in-memory repository bundle. It does not
    resolve, mount, or inspect hidden-test files.
    """
    if type(result) is not FrozenLiveCellResult:
        raise FrozenLiveExecutionPlanError("invalid_frozen_live_cell_result")
    # Reuse the closed serializer as a validation boundary before identity minting.
    frozen_model_output_sha256(result)
    from recallpack.evaluation_docker import _directory_tree_sha256
    from recallpack.isolation import ProductionExecutionIdentity

    with tempfile.TemporaryDirectory(prefix="recallpack-v4-frozen-identity-") as temporary:
        repository_root = materialize_frozen_repository(
            result.contract,
            Path(temporary) / "repository-snapshot",
        )
        repository_snapshot_sha256 = _directory_tree_sha256(repository_root)
    return ProductionExecutionIdentity(
        execution_manifest_sha256=result.execution_manifest_sha256,
        scenario_id=result.contract.scenario_slot,
        slot_index=result.cell.slot_index,
        attempt_no=result.attempt_no,
        repository_snapshot_sha256=repository_snapshot_sha256,
        hidden_test_tree_sha256=result.contract.hidden_test_content_sha256,
    )


def append_authorized_frozen_runner_output(
    authorized: AuthorizedFrozenLiveCell,
    *,
    isolated_result: Any,
    evaluator_contract: Mapping[str, Any],
    production_execution_identity: Any,
    runner_output_journal: Any,
) -> dict[str, Any]:
    """Append one production-receipted frozen result to the evaluator journal.

    A test-only injected runner cannot cross this boundary: the existing
    evaluator adapter and ``ProductionRunnerOutputJournal`` both require an
    authenticated production execution receipt. The returned envelope is a
    detached copy; the journal remains the evidence authority.
    """
    if type(authorized) is not AuthorizedFrozenLiveCell:
        raise FrozenLiveExecutionPlanError("invalid_authorized_frozen_live_cell")
    result = authorized.result
    if type(authorized.output_fixation) is not FrozenOutputFixation or not _matches_frozen_output_fixation(
        authorized.output_fixation,
        result,
    ):
        raise FrozenLiveExecutionPlanError("frozen_output_fixation_mismatch")
    _validate_frozen_production_identity(
        result,
        production_execution_identity,
    )
    from recallpack.evaluation_docker import _directory_tree_sha256
    from recallpack.evaluation_evidence_adapter import (
        build_v4_diagnostic_runner_outputs,
    )
    from recallpack.evaluation_variants import (
        V4DiagnosticScenarioResult,
        V4DiagnosticVariantResult,
    )
    from recallpack.evidence_pipeline import ProductionRunnerOutputJournal

    if type(runner_output_journal) is not ProductionRunnerOutputJournal:
        raise FrozenLiveExecutionPlanError("invalid_production_runner_output_journal")
    with tempfile.TemporaryDirectory(prefix="recallpack-v4-frozen-envelope-") as temporary:
        fixture_root = Path(temporary) / "fixture"
        fixture_root.mkdir()
        repository_root = materialize_frozen_repository(
            result.contract,
            fixture_root / "repo_snapshot",
        )
        if (
            _directory_tree_sha256(repository_root)
            != production_execution_identity.repository_snapshot_sha256
        ):
            raise FrozenLiveExecutionPlanError("production_identity_mismatch")
        variant = V4DiagnosticVariantResult(
            variant_id=result.cell.variant_id,
            selected_context=copy.deepcopy([dict(item) for item in result.selection.selected_context]),
            selected_source_refs=tuple(result.selection.selected_source_refs),
            model_visible_context=result.selection.model_visible_context,
            model_visible_context_sha256=result.selection.model_visible_context_sha256,
            exact_token_count=result.selection.exact_token_count,
            budget_comparable=result.selection.budget_comparable,
            provider_traces=copy.deepcopy(list(result.provider_traces)),
            downstream=copy.deepcopy(result.downstream),
            generated_files=copy.deepcopy(list(result.generated_files)),
            execution_trace={
                **copy.deepcopy(result.execution_trace),
                "frozen_output_fixation": {
                    "model_output_sha256": authorized.output_fixation.model_output_sha256,
                    "generated_files_sha256": authorized.output_fixation.generated_files_sha256,
                },
            },
        )
        diagnostic = V4DiagnosticScenarioResult(
            scenario_id=result.contract.scenario_slot,
            variants={result.cell.variant_id: variant},
            strongest_baseline_variant_id=None,
            strongest_baseline_variant_ids=(),
            strongest_baseline_full_suite_passed=None,
            recallpack_full_suite_passed=None,
            classification="frozen_live_execution",
            evidence_status="pre_isolation",
            evidence_bindings={},
            limitations=(
                "One frozen production cell; claim aggregation remains evaluator-owned.",
            ),
        )
        try:
            output = build_v4_diagnostic_runner_outputs(
                diagnostic,
                fixture_root=fixture_root,
                isolated_results={result.cell.variant_id: isolated_result},
                evaluator_contract=evaluator_contract,
                production_execution_identities={
                    result.cell.variant_id: production_execution_identity,
                },
            )[result.cell.variant_id]
            runner_output_journal.append(
                scenario_id=result.contract.scenario_slot,
                slot_index=result.cell.slot_index,
                variant_id=result.cell.variant_id,
                attempt_no=result.attempt_no,
                output=output,
                isolated_result=isolated_result,
                expected_identity=production_execution_identity,
            )
        except (TypeError, ValueError, RuntimeError) as exc:
            raise FrozenLiveExecutionPlanError(
                "production_runner_output_rejected"
            ) from exc
    return copy.deepcopy(output)


def _validate_frozen_production_identity(
    result: FrozenLiveCellResult,
    identity: Any,
) -> None:
    from recallpack.isolation import ProductionExecutionIdentity

    if (
        type(identity) is not ProductionExecutionIdentity
        or identity.execution_manifest_sha256 != result.execution_manifest_sha256
        or identity.scenario_id != result.contract.scenario_slot
        or identity.slot_index != result.cell.slot_index
        or identity.attempt_no != result.attempt_no
        or identity.hidden_test_tree_sha256 != result.contract.hidden_test_content_sha256
    ):
        raise FrozenLiveExecutionPlanError("production_identity_mismatch")


def run_frozen_live_cell_isolated(
    result: FrozenLiveCellResult,
    *,
    hidden_test_root: str | Path,
    evaluator_contract: Mapping[str, Any],
    suite_runner: Callable[..., Any] | None = None,
    production_execution_identity: Any = None,
    output_fixation: FrozenOutputFixation | None = None,
) -> Any:
    """Hand one fixed patch to the existing isolated evaluator.

    This function contains no Docker invocation of its own. A caller must inject
    a test runner or deliberately omit it to use the established production
    runner. The hidden-test root is hash-verified before the evaluator receives
    a disposable repository materialized only from the frozen contract.
    """
    if type(result) is not FrozenLiveCellResult:
        raise FrozenLiveExecutionPlanError("invalid_frozen_live_cell_result")
    if (
        result.execution_trace.get("execution_manifest_sha256")
        != result.execution_manifest_sha256
        or not _is_sha256(result.execution_manifest_sha256)
        or type(result.contract) is not FrozenScenarioExecutionContract
        or not _is_sha256(result.generated_files_sha256)
    ):
        raise FrozenLiveExecutionPlanError("invalid_frozen_live_cell_result")
    if result.generated_files_sha256 != _frozen_generated_files_sha256(
        result.generated_files
    ):
        raise FrozenLiveExecutionPlanError("frozen_patch_digest_mismatch")
    outcome_status = result.attempt_outcome.get("status")
    if outcome_status == "invalidated":
        raise FrozenLiveExecutionPlanError(
            "technical_pre_isolation_attempt_requires_retry"
        )
    patch_rejected = (
        result.downstream.get("accepted") is not True or not result.generated_files
    )
    if suite_runner is None and production_execution_identity is None:
        raise FrozenLiveExecutionPlanError("production_identity_required")
    if production_execution_identity is not None:
        _validate_frozen_production_identity(result, production_execution_identity)
        if type(output_fixation) is not FrozenOutputFixation:
            raise FrozenLiveExecutionPlanError("production_output_fixation_required")
        if not _matches_frozen_output_fixation(output_fixation, result):
            raise FrozenLiveExecutionPlanError("frozen_output_fixation_mismatch")
        if suite_runner is not None:
            raise FrozenLiveExecutionPlanError("production_isolation_requires_default_runner")
        if patch_rejected:
            if (
                outcome_status != "adverse"
                or result.attempt_outcome.get("stage") != "patch_generation"
                or result.generated_files
            ):
                raise FrozenLiveExecutionPlanError(
                    "non_patch_rejection_requires_pre_isolation_retention"
                )
            from recallpack.evaluation_docker import (
                seal_frozen_production_patch_rejection,
            )

            with tempfile.TemporaryDirectory(
                prefix="recallpack-v4-frozen-nonexecution-"
            ) as temporary:
                repository_snapshot_root = materialize_frozen_repository(
                    result.contract,
                    Path(temporary) / "repository-snapshot",
                )
                return seal_frozen_production_patch_rejection(
                    scenario_id=result.contract.scenario_slot,
                    variant_id=result.cell.variant_id,
                    repository_snapshot_root=repository_snapshot_root,
                    generated_files=result.generated_files,
                    downstream=result.downstream,
                    production_execution_identity=production_execution_identity,
                )
    if patch_rejected:
        raise FrozenLiveExecutionPlanError("patch_not_executable_before_hidden_reveal")
    from recallpack.evaluation_docker import run_frozen_isolated_variant

    with tempfile.TemporaryDirectory(prefix="recallpack-v4-frozen-isolated-") as temporary:
        repository_snapshot_root = materialize_frozen_repository(
            result.contract,
            Path(temporary) / "repository-snapshot",
        )
        verify_frozen_hidden_test_root(result.contract, hidden_test_root)
        kwargs: dict[str, Any] = {
            "scenario_id": result.contract.scenario_slot,
            "variant_id": result.cell.variant_id,
            "repository_snapshot_root": repository_snapshot_root,
            "hidden_test_root": hidden_test_root,
            "generated_files": result.generated_files,
            "downstream": result.downstream,
            "allowed_paths": result.contract.allowed_edit_paths,
            "evaluator_contract": evaluator_contract,
            "production_execution_identity": production_execution_identity,
        }
        if suite_runner is not None:
            kwargs["suite_runner"] = suite_runner
        return run_frozen_isolated_variant(**kwargs)


def _matches_frozen_output_fixation(
    fixation: FrozenOutputFixation,
    result: FrozenLiveCellResult,
) -> bool:
    """Match an authority-minted binding against the exact current result."""
    return (
        fixation.execution_manifest_sha256 == result.execution_manifest_sha256
        and fixation.slot_id == result.cell.slot_id
        and fixation.slot_index == result.cell.slot_index
        and fixation.scenario_slot == result.contract.scenario_slot
        and fixation.variant_id == result.cell.variant_id
        and fixation.attempt_no == result.attempt_no
        and fixation.model_output_sha256 == frozen_model_output_sha256(result)
        and fixation.generated_files_sha256 == result.generated_files_sha256
    )


def _patch_trace_record(
    prepared: PreparedDownstreamPatch,
    *,
    selected_context_count: int,
) -> dict[str, Any]:
    if prepared.provider_trace is not None:
        return prepared.provider_trace.to_v4_record()
    return {
        "role": "patch_generation",
        "provider_family": "invalid_provider_output",
        "model_name": "unknown",
        "request_purpose": "generate_patch_from_goal_and_selected_context",
        "input_item_count": 1 + selected_context_count,
        "input_token_estimate": 0,
        "output_item_count": 0,
        "live": False,
        "deterministic_fallback": False,
        "request_id_present": False,
        "token_usage": {},
    }


def _selection_failure_result(
    *,
    plan: FrozenLiveExecutionPlan,
    cell: FrozenLiveExecutionCell,
    contract: FrozenScenarioExecutionContract,
    attempt_no: int,
    code: Any,
    retryable: bool,
    provider_role: str | None,
    provider_error: ProviderError | None,
    prior_traces: tuple[ProviderTrace, ...],
    provider_error_trace_retained: bool,
) -> FrozenLiveCellResult:
    """Retain a closed selection failure without allowing patch or hidden access."""
    failure_code = _safe_selection_failure_code(code)
    retrieval_traces = list(prior_traces)
    if (
        provider_role is not None
        and provider_error is not None
        and not provider_error_trace_retained
    ):
        retrieval_traces.append(
            _selection_provider_error_trace(provider_role, provider_error)
        )
    selection = _build_context_selection(
        variant_id=cell.variant_id,
        selected=[],
        retrieval_traces=retrieval_traces,
        budget_comparable=True,
        execution_trace={
            "selection_source": "provider_or_runtime_failure",
            "selection_failure_code": failure_code,
            "selection_failure_role": provider_role or "runtime",
            "retained_prior_trace_count": len(prior_traces),
        },
    )
    retryable_technical_failure = (
        retryable and _retryable_frozen_failure_code(failure_code, plan)
    )
    attempt_outcome = (
        {
            "status": "invalidated",
            "stage": "selection",
            "code": failure_code,
        }
        if retryable_technical_failure
        else {
            "status": "adverse",
            "stage": "selection",
            "code": failure_code,
        }
    )
    downstream = {
        "execution_mode": "selection_failed",
        "variant_id": cell.variant_id,
        "accepted": False,
        "error": failure_code,
        "patch_diff": "",
        "test_status": "not_run_selection_failed",
        "causal_reason": "selection failed before patch generation",
        "patch_generation": {
            "used_gold_patch_variants": False,
            "output_paths": [],
        },
    }
    execution_trace = {
        "execution_manifest_sha256": plan.execution_manifest_sha256,
        "slot_id": cell.slot_id,
        "slot_index": cell.slot_index,
        "attempt_no": attempt_no,
        "scenario_slot": cell.scenario_slot,
        "variant_id": cell.variant_id,
        "repetition": cell.repetition,
        "selection": dict(selection.execution_trace),
        "selected_context_sha256": selection.model_visible_context_sha256,
        "selected_context_token_count": selection.exact_token_count,
        "patch_generation_accepted": False,
        "isolated_evaluation": "not_run",
    }
    generated_files: tuple[dict[str, str], ...] = ()
    return FrozenLiveCellResult(
        cell=cell,
        execution_manifest_sha256=plan.execution_manifest_sha256,
        attempt_no=attempt_no,
        contract=contract,
        selection=selection,
        downstream=downstream,
        generated_files=generated_files,
        generated_files_sha256=_frozen_generated_files_sha256(generated_files),
        provider_traces=selection.provider_traces,
        attempt_outcome=attempt_outcome,
        execution_trace=execution_trace,
    )


def _selection_provider_error_trace(
    role: str,
    error: ProviderError,
    *,
    request_purpose: str | None = None,
) -> ProviderTrace:
    if role not in {"embedding", "rerank"}:
        raise FrozenLiveExecutionPlanError("invalid_selection_provider_role")
    model_id = error.model_id if _safe_public_identifier(error.model_id) else "unknown"
    return ProviderTrace(
        provider_name="qwen-cloud" if error.provider_name == "qwen-cloud" else "provider",
        model_id=model_id,
        provider_role=role,
        request_purpose=(
            request_purpose
            or (
                "candidate_memory_retrieval_query"
                if role == "embedding"
                else "rank_raw_session_events_for_handoff"
            )
        ),
        input_item_count=0,
        input_token_estimate=0,
        output_item_count=0,
        is_live=error.provider_name == "qwen-cloud",
        deterministic_fallback_status="provider_error",
        request_id=error.request_id,
        usage=_safe_provider_usage(error.usage),
    )


def _safe_provider_usage(value: Any) -> dict[str, int]:
    if not isinstance(value, Mapping):
        return {}
    aliases = {
        "input_tokens": ("input_tokens", "prompt_tokens"),
        "output_tokens": ("output_tokens", "completion_tokens"),
        "total_tokens": ("total_tokens",),
    }
    normalized: dict[str, int] = {}
    for destination, source_keys in aliases.items():
        for source_key in source_keys:
            raw_value = value.get(source_key)
            if type(raw_value) is int and raw_value >= 0:
                normalized[destination] = raw_value
                break
    if "total_tokens" not in normalized and {
        "input_tokens",
        "output_tokens",
    } <= set(normalized):
        normalized["total_tokens"] = (
            normalized["input_tokens"] + normalized["output_tokens"]
        )
    return normalized


def _safe_selection_failure_code(value: Any) -> str:
    return value if _safe_public_identifier(value) else "provider_failure"


def _retryable_frozen_failure_code(
    code: str,
    plan: FrozenLiveExecutionPlan,
) -> bool:
    return (
        code in plan.technical_failure_codes
        and code != "provider_operator_action_required"
    )


def _frozen_selection_runtime_failure_code(
    error: FrozenLiveExecutionPlanError,
    plan: FrozenLiveExecutionPlan,
) -> str | None:
    prefix, separator, raw_code = str(error).partition(": ")
    if (
        not separator
        or prefix
        not in {
            "recallpack_observe_failed",
            "recallpack_compile_failed",
            "recall_time_observe_failed",
        }
    ):
        return None
    code = _safe_selection_failure_code(raw_code)
    return code if code in plan.technical_failure_codes else None


def _selection_response_failure_code(error: Any, status_code: Any) -> str:
    if _safe_public_identifier(error):
        return error
    if type(status_code) is int and 100 <= status_code <= 599:
        return f"selection_runtime_http_{status_code}"
    return "selection_runtime_failure"


def _provider_trace_snapshot(*providers: object) -> tuple[ProviderTrace, ...]:
    traces: list[ProviderTrace] = []
    for provider in providers:
        raw_traces = getattr(provider, "traces", None)
        if not isinstance(raw_traces, list):
            continue
        traces.extend(trace for trace in raw_traces if isinstance(trace, ProviderTrace))
    return tuple(traces)


def _frozen_generated_files_sha256(
    generated_files: tuple[dict[str, str], ...],
) -> str:
    if not isinstance(generated_files, tuple):
        raise FrozenLiveExecutionPlanError("invalid_frozen_patch_files")
    try:
        return hashlib.sha256(
            canonicalize_review_json([dict(item) for item in generated_files])
        ).hexdigest()
    except (TypeError, ValueError) as exc:
        raise FrozenLiveExecutionPlanError("invalid_frozen_patch_files") from exc


def select_frozen_context(
    contract: FrozenScenarioExecutionContract,
    *,
    variant_id: str,
    providers: FrozenExecutionProviders,
) -> FrozenContextSelection:
    """Select model-visible handoff context for a frozen baseline cell.

    This function currently owns raw-history, semantic-rerank, and
    recency-aware selection. Lifecycle variants are added separately so their
    write-time and recall-time state transitions can be tested independently.
    """
    if type(contract) is not FrozenScenarioExecutionContract:
        raise FrozenLiveExecutionPlanError("invalid_frozen_scenario_contract")
    if type(providers) is not FrozenExecutionProviders:
        raise FrozenLiveExecutionPlanError("invalid_execution_providers")
    raw_candidates = [_context_from_frozen_event(event) for event in contract.events[:-1]]
    if not raw_candidates:
        raise FrozenLiveExecutionPlanError("missing_frozen_memory_events")
    input_source_refs = [item["source_ref"] for item in raw_candidates]

    if variant_id == "raw_full_history":
        return _build_context_selection(
            variant_id=variant_id,
            selected=raw_candidates,
            retrieval_traces=[],
            budget_comparable=False,
            execution_trace={
                "selection_source": "raw_full_history_unfiltered",
                "candidate_count": len(raw_candidates),
                "input_source_refs": input_source_refs,
            },
        )
    if variant_id == "recallpack":
        return _select_recallpack_context(contract, providers)
    if variant_id not in {
        "semantic_rerank",
        "recency_aware",
        "recall_time_resolver",
    }:
        raise FrozenLiveExecutionPlanError(f"unsupported_selection_variant: {variant_id}")
    embedding_provider = _TracingEmbeddingProvider(
        _required_provider(
            providers.embedding_provider_factory,
            "embedding_provider_factory",
        )
    )

    ranked, retrieval_traces, execution_trace = _semantic_rank_frozen(
        goal=contract.goal,
        candidates=raw_candidates,
        embedding_provider=embedding_provider,
        rerank_provider=_required_provider(
            providers.rerank_provider_factory,
            "rerank_provider_factory",
        ),
    )
    if variant_id == "recall_time_resolver":
        return _select_recall_time_resolver_context(
            contract,
            providers,
            ranked=ranked,
            retrieval_traces=retrieval_traces,
            semantic_embedding_trace_count=len(embedding_provider.traces),
            embedding_provider=embedding_provider,
            execution_trace=execution_trace,
        )
    if variant_id == "recency_aware":
        rerank_positions = {
            item["source_ref"]: index for index, item in enumerate(ranked)
        }
        ranked.sort(
            key=lambda item: (
                -_timestamp_key(item["observed_at"]),
                rerank_positions[item["source_ref"]],
            )
        )
        execution_trace = dict(execution_trace)
        execution_trace.update(
            {
                "selection_source": "embedding_top_20_then_recency",
                "recency_order": [item["source_ref"] for item in ranked],
            }
        )
    selected = list(BudgetSelector(512).select(ranked).memories)
    return _build_context_selection(
        variant_id=variant_id,
        selected=selected,
        retrieval_traces=retrieval_traces,
        budget_comparable=True,
        execution_trace=execution_trace,
    )


def _select_recallpack_context(
    contract: FrozenScenarioExecutionContract,
    providers: FrozenExecutionProviders,
) -> FrozenContextSelection:
    memory_provider = _required_provider(
        providers.memory_provider_factory,
        "memory_provider_factory",
    )
    embedding_provider = _TracingEmbeddingProvider(
        _required_provider(
            providers.embedding_provider_factory,
            "embedding_provider_factory",
        )
    )
    ranker = ProviderRanker(
        _required_provider(
            providers.rerank_provider_factory,
            "rerank_provider_factory",
        )
    )
    decider = ProviderMemoryDecider(memory_provider)
    project_id = f"v4-live-{contract.scenario_slot}"
    components = {"retry", "auth", "cache", "config", contract.component}
    observations: list[dict[str, str]] = []
    with tempfile.TemporaryDirectory(prefix="recallpack-v4-live-runtime-") as temporary:
        store = SqliteEventStore(Path(temporary) / "runtime.sqlite3")
        runtime = ObserveRuntime(
            store=store,
            decider=decider,
            components=components,
            embedding_provider=embedding_provider,
            turnstile_registry=ProjectTurnstileRegistry(),
        )
        for sequence_no, event in enumerate(contract.events[:-1], start=1):
            session_id, event_id = _source_ref_parts(event.source_ref)
            response = runtime.observe(
                ObserveRequest(
                    project_id=project_id,
                    session_id=session_id,
                    event_id=event_id,
                    sequence_no=sequence_no,
                    actor=event.actor,
                    kind=event.kind,
                    observed_at=event.observed_at,
                    text=event.summary,
                ),
                now=sequence_no,
            )
            if response.status_code != 200 or response.final_result is None:
                raise _FrozenSelectionRuntimeFailure(
                    code=_selection_response_failure_code(
                        response.error,
                        response.status_code,
                    ),
                    prior_traces=_provider_trace_snapshot(
                        decider,
                        embedding_provider,
                        ranker,
                    ),
                )
            operation = response.final_result.get("operation")
            if not isinstance(operation, str):
                raise FrozenLiveExecutionPlanError("recallpack_observe_result_invalid")
            observations.append(
                {"source_ref": event.source_ref, "operation": operation}
            )
        compiled = CompileService(
            store=store,
            ranker=ranker,
            embedding_provider=embedding_provider,
            components=components,
        ).compile(
            CompileRequest(
                project_id=project_id,
                goal=contract.goal,
                component=contract.component,
                budget_tokens=512,
            )
        )
    if compiled.status_code != 200:
        raise _FrozenSelectionRuntimeFailure(
            code=_selection_response_failure_code(
                compiled.error,
                compiled.status_code,
            ),
            prior_traces=_provider_trace_snapshot(
                decider,
                embedding_provider,
                ranker,
            ),
        )
    trace = dict(compiled.trace)
    trace.update(
        {
            "selection_source": "persisted_write_time_lifecycle",
            "persisted_lifecycle_used": True,
            "observations": observations,
        }
    )
    return _build_context_selection(
        variant_id="recallpack",
        selected=list(compiled.pack.memories),
        retrieval_traces=[
            *decider.traces,
            *embedding_provider.traces,
            *ranker.traces,
        ],
        budget_comparable=True,
        execution_trace=trace,
    )


def _select_recall_time_resolver_context(
    contract: FrozenScenarioExecutionContract,
    providers: FrozenExecutionProviders,
    *,
    ranked: list[dict[str, Any]],
    retrieval_traces: list[ProviderTrace],
    semantic_embedding_trace_count: int,
    embedding_provider: _TracingEmbeddingProvider,
    execution_trace: Mapping[str, Any],
) -> FrozenContextSelection:
    decider = ProviderMemoryDecider(
        _required_provider(
            providers.memory_provider_factory,
            "memory_provider_factory",
        )
    )
    candidate_source_refs = {item["source_ref"] for item in ranked[:20]}
    project_id = f"v4-recall-time-{contract.scenario_slot}"
    components = {"retry", "auth", "cache", "config", contract.component}
    observations: list[dict[str, str]] = []
    with tempfile.TemporaryDirectory(prefix="recallpack-v4-recall-time-") as temporary:
        store = SqliteEventStore(Path(temporary) / "resolver.sqlite3")
        runtime = ObserveRuntime(
            store=store,
            decider=decider,
            components=components,
            embedding_provider=embedding_provider,
            turnstile_registry=ProjectTurnstileRegistry(),
        )
        sequence_no = 0
        for event in contract.events[:-1]:
            if event.source_ref not in candidate_source_refs:
                continue
            sequence_no += 1
            session_id, event_id = _source_ref_parts(event.source_ref)
            response = runtime.observe(
                ObserveRequest(
                    project_id=project_id,
                    session_id=session_id,
                    event_id=event_id,
                    sequence_no=sequence_no,
                    actor=event.actor,
                    kind=event.kind,
                    observed_at=event.observed_at,
                    text=event.summary,
                ),
                now=sequence_no,
            )
            if response.status_code != 200 or response.final_result is None:
                raise _FrozenSelectionRuntimeFailure(
                    code=_selection_response_failure_code(
                        response.error,
                        response.status_code,
                    ),
                    prior_traces=tuple(
                        [
                            *retrieval_traces,
                            *decider.traces,
                            *embedding_provider.traces[semantic_embedding_trace_count:],
                        ]
                    ),
                )
            operation = response.final_result.get("operation")
            if not isinstance(operation, str):
                raise FrozenLiveExecutionPlanError("recall_time_observe_result_invalid")
            observations.append({"source_ref": event.source_ref, "operation": operation})
        active_by_source = {
            f"{memory.source_ref.session_id}:{memory.source_ref.event_id}": memory
            for memory in store.active_memories(project_id)
        }
    resolved = [
        _context_from_memory(active_by_source[item["source_ref"]])
        for item in ranked
        if item["source_ref"] in active_by_source
    ]
    selected = list(BudgetSelector(512).select(resolved).memories)
    trace = dict(execution_trace)
    trace.update(
        {
            "selection_source": "recall_time_conflict_resolution",
            "persisted_lifecycle_used": False,
            "resolved_sources": [item["source_ref"] for item in resolved],
            "observations": observations,
        }
    )
    return _build_context_selection(
        variant_id="recall_time_resolver",
        selected=selected,
        retrieval_traces=[
            *retrieval_traces,
            *decider.traces,
            *embedding_provider.traces[semantic_embedding_trace_count:],
        ],
        budget_comparable=True,
        execution_trace=trace,
    )


def _build_context_selection(
    *,
    variant_id: str,
    selected: list[dict[str, Any]],
    retrieval_traces: list[ProviderTrace],
    budget_comparable: bool,
    execution_trace: dict[str, Any],
) -> FrozenContextSelection:
    selected_source_refs = tuple(_candidate_source_ref(item) for item in selected)
    model_visible_selected = tuple(_model_visible_candidate(item) for item in selected)
    context = SelectedPack(memories=list(model_visible_selected)).to_canonical_json()
    token_count = count_canonical_json_tokens(context)
    if budget_comparable and token_count > 512:
        raise FrozenLiveExecutionPlanError("model_visible_context_exceeds_budget")
    return FrozenContextSelection(
        variant_id=variant_id,
        selected_context=model_visible_selected,
        selected_source_refs=selected_source_refs,
        model_visible_context=context,
        model_visible_context_sha256=hashlib.sha256(context.encode("utf-8")).hexdigest(),
        exact_token_count=token_count,
        budget_comparable=budget_comparable,
        provider_traces=tuple(trace.to_v4_record() for trace in retrieval_traces),
        execution_trace=dict(execution_trace),
    )


def _semantic_rank_frozen(
    *,
    goal: str,
    candidates: list[dict[str, Any]],
    embedding_provider: Any,
    rerank_provider: Any,
) -> tuple[list[dict[str, Any]], list[ProviderTrace], dict[str, Any]]:
    try:
        query_result = embedding_provider.embed_query(goal)
    except ProviderError as exc:
        raise _FrozenSelectionProviderFailure(
            role="embedding",
            error=exc,
            prior_traces=tuple(getattr(embedding_provider, "traces", ())),
            provider_error_trace_retained=True,
        ) from exc
    query = validated_query_vector(query_result.embedding)
    traces = [query_result.trace]
    scored: list[tuple[float, int, dict[str, Any]]] = []
    for index, candidate in enumerate(candidates):
        try:
            document_result = embedding_provider.embed_document(
                _candidate_document(candidate)
            )
        except ProviderError as exc:
            raise _FrozenSelectionProviderFailure(
                role="embedding",
                error=exc,
                prior_traces=tuple(getattr(embedding_provider, "traces", traces)),
                provider_error_trace_retained=True,
            ) from exc
        document = validated_vector(document_result.embedding)
        traces.append(document_result.trace)
        scored.append((cosine_similarity(query, document), index, candidate))
    scored.sort(key=lambda row: (-row[0], row[1]))
    top_twenty = scored[:20]
    documents = [_candidate_document(row[2]) for row in top_twenty]
    try:
        rerank_result = rerank_provider.rerank(
            goal=goal,
            documents=documents,
            instruct="rank raw session events for a coding-agent handoff",
        )
    except ProviderError as exc:
        raise _FrozenSelectionProviderFailure(
            role="rerank",
            error=exc,
            prior_traces=tuple(traces),
        ) from exc
    _validate_rerank_indexes(rerank_result.ranked_indexes, len(top_twenty))
    traces.append(rerank_result.trace)
    ranked = [top_twenty[index][2] for index in rerank_result.ranked_indexes]
    return ranked, traces, {
        "selection_source": "embedding_top_20_then_rerank",
        "embedding_order": [row[2]["source_ref"] for row in scored],
        "rerank_order": [item["source_ref"] for item in ranked],
        "candidate_count": len(candidates),
        "input_source_refs": [item["source_ref"] for item in candidates],
        "rerank_input_count": len(top_twenty),
    }


def _required_provider(factory: Callable[[], Any] | None, name: str) -> Any:
    if not callable(factory):
        raise FrozenLiveExecutionPlanError(f"missing_{name}")
    try:
        provider = factory()
    except Exception as exc:
        raise FrozenLiveExecutionPlanError(f"provider_factory_failed: {name}") from exc
    if provider is None:
        raise FrozenLiveExecutionPlanError(f"missing_{name}")
    return provider


class _TracingEmbeddingProvider:
    """Capture every provider trace without changing the embedding contract."""

    def __init__(self, provider: Any) -> None:
        self._provider = provider
        self.traces: list[ProviderTrace] = []

    def embed_query(self, text: str) -> Any:
        try:
            result = self._provider.embed_query(text)
        except ProviderError as exc:
            self.traces.append(
                _selection_provider_error_trace(
                    "embedding",
                    exc,
                    request_purpose="candidate_memory_retrieval_query",
                )
            )
            raise
        self.traces.append(result.trace)
        return result

    def embed_document(self, text: str) -> Any:
        try:
            result = self._provider.embed_document(text)
        except ProviderError as exc:
            self.traces.append(
                _selection_provider_error_trace(
                    "embedding",
                    exc,
                    request_purpose="candidate_memory_retrieval_document",
                )
            )
            raise
        self.traces.append(result.trace)
        return result


def _source_ref_parts(source_ref: str) -> tuple[str, str]:
    session_id, separator, event_id = source_ref.partition(":")
    if not separator or not session_id or not event_id or ":" in event_id:
        raise FrozenLiveExecutionPlanError("invalid_frozen_source_ref")
    return session_id, event_id


def _validate_rerank_indexes(indexes: Any, expected_count: int) -> None:
    if (
        not isinstance(indexes, list)
        or any(type(index) is not int for index in indexes)
        or sorted(indexes) != list(range(expected_count))
    ):
        raise FrozenLiveExecutionPlanError("invalid_rerank_result")


def _context_from_frozen_event(event: FrozenScenarioEvent) -> dict[str, Any]:
    return {
        "id": event.source_ref.replace(":", "_"),
        "type": "raw_event",
        "subject": "session_event",
        "scope": "raw_history",
        "text": event.summary,
        "actor": event.actor,
        "kind": event.kind,
        "source_ref": event.source_ref,
        "observed_at": event.observed_at,
    }


def _context_from_memory(memory: Any) -> dict[str, Any]:
    source_ref = getattr(memory, "source_ref", None)
    session_id = getattr(source_ref, "session_id", None)
    event_id = getattr(source_ref, "event_id", None)
    scope_level = getattr(memory, "scope_level", None)
    component = getattr(memory, "component", None)
    scope = "project" if scope_level == "project" else f"{scope_level}:{component}"
    values = {
        "id": getattr(memory, "id", None),
        "type": getattr(memory, "type", None),
        "subject": getattr(memory, "subject", None),
        "scope": scope,
        "text": getattr(memory, "text", None),
        "actor": getattr(memory, "source_actor", None),
        "kind": "memory",
        "source_ref": f"{session_id}:{event_id}",
    }
    if any(not isinstance(value, str) or not value for value in values.values()):
        raise FrozenLiveExecutionPlanError("invalid_recall_time_memory")
    return values


def _candidate_source_ref(candidate: Mapping[str, Any]) -> str:
    source_ref = candidate.get("source_ref")
    if not isinstance(source_ref, str) or not source_ref:
        raise FrozenLiveExecutionPlanError("selected_candidate_lacks_provenance")
    return source_ref


def _model_visible_candidate(candidate: Mapping[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in candidate.items()
        if key not in {"id", "source_ref", "observed_at"}
    }


def _candidate_document(candidate: Mapping[str, Any]) -> str:
    return (
        f"type={candidate['type']}\n"
        f"scope={candidate['scope']}\n"
        f"actor={candidate['actor']}\n"
        f"kind={candidate['kind']}\n"
        f"text={candidate['text']}"
    )


def _timestamp_key(value: Any) -> int:
    if not isinstance(value, str):
        raise FrozenLiveExecutionPlanError("invalid_frozen_observed_at")
    digits = "".join(character for character in value if character.isdigit())
    if len(digits) != 14:
        raise FrozenLiveExecutionPlanError("invalid_frozen_observed_at")
    return int(digits)


def _repository_bundle_files(
    bundle: Mapping[str, Any],
    slot: str,
) -> tuple[FrozenRepositoryFile, ...]:
    if (
        bundle.get("record_type") != "deterministic_file_bundle"
        or bundle.get("scenario_slot") != slot
        or bundle.get("purpose") != "fixture"
        or not isinstance(bundle.get("files"), list)
        or not bundle["files"]
    ):
        raise FrozenLiveExecutionPlanError(f"invalid_repository_snapshot: {slot}")
    paths: set[str] = set()
    files: list[FrozenRepositoryFile] = []
    for item in bundle["files"]:
        if not isinstance(item, Mapping):
            raise FrozenLiveExecutionPlanError(f"invalid_repository_snapshot: {slot}")
        path = _canonical_repository_path(item.get("path"))
        encoded = item.get("content_base64")
        byte_count = item.get("bytes")
        expected_sha256 = item.get("sha256")
        if (
            path in paths
            or not isinstance(encoded, str)
            or type(byte_count) is not int
            or byte_count < 0
            or not _is_sha256(expected_sha256)
        ):
            raise FrozenLiveExecutionPlanError(f"invalid_repository_snapshot: {slot}")
        try:
            payload = base64.b64decode(encoded.encode("ascii"), validate=True)
        except (UnicodeEncodeError, binascii.Error) as exc:
            raise FrozenLiveExecutionPlanError(
                f"invalid_repository_snapshot: {slot}"
            ) from exc
        if len(payload) != byte_count or hashlib.sha256(payload).hexdigest() != expected_sha256:
            raise FrozenLiveExecutionPlanError(f"invalid_repository_snapshot: {slot}")
        paths.add(path)
        files.append(FrozenRepositoryFile(path=path, content=payload))
    return tuple(files)


def _canonical_repository_path(value: Any) -> str:
    if not isinstance(value, str) or not value or not value.isascii():
        raise FrozenLiveExecutionPlanError("invalid_repository_relative_path")
    path = PurePosixPath(value)
    if (
        path.is_absolute()
        or path.as_posix() != value
        or any(part in {"", ".", ".."} for part in path.parts)
    ):
        raise FrozenLiveExecutionPlanError("invalid_repository_relative_path")
    return value


def _is_sha256(value: Any) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )
