from __future__ import annotations

import hashlib
import json
import math
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from recallpack.budget import BudgetSelector, SelectedPack, count_canonical_json_tokens
from recallpack.compile import CompileRequest, CompileService
from recallpack.downstream import DeterministicPolicyPatchProvider, prepare_downstream_patch
from recallpack.locking import ProjectTurnstileRegistry
from recallpack.observe import ObserveRequest, ObserveRuntime
from recallpack.providers import (
    DeterministicKeywordEmbeddingProvider,
    DeterministicKeywordRerankProvider,
    ProviderRanker,
    ProviderTrace,
)
from recallpack.storage import SqliteEventStore


V4_VARIANT_IDS = (
    "raw_full_history",
    "semantic_rerank",
    "recency_aware",
    "recall_time_resolver",
    "recallpack",
)
_COMPARATOR_IDS = V4_VARIANT_IDS[1:4]
_EVENT_FIELDS = {
    "source_ref",
    "observed_at",
    "actor",
    "kind",
    "summary",
    "model_visible",
    "authored_summary",
}


@dataclass(frozen=True)
class V4DiagnosticVariantResult:
    variant_id: str
    selected_context: list[dict[str, Any]]
    selected_source_refs: tuple[str, ...]
    model_visible_context: str
    model_visible_context_sha256: str
    exact_token_count: int
    budget_comparable: bool
    provider_traces: list[dict[str, Any]]
    downstream: dict[str, Any]
    generated_files: list[dict[str, str]]
    execution_trace: dict[str, Any]


@dataclass(frozen=True)
class V4DiagnosticScenarioResult:
    scenario_id: str
    variants: dict[str, V4DiagnosticVariantResult]
    strongest_baseline_variant_id: str | None
    strongest_baseline_variant_ids: tuple[str, ...]
    strongest_baseline_full_suite_passed: bool | None
    recallpack_full_suite_passed: bool | None
    classification: str
    evidence_status: str
    evidence_bindings: dict[str, str]
    limitations: tuple[str, ...]


@dataclass(frozen=True)
class _DownstreamFixture:
    root: Path
    gold: dict[str, Any]


class _ScenarioLifecycleDecider:
    def __init__(self, component: str) -> None:
        self._component = component
        self.traces: list[ProviderTrace] = []

    def decide_memory_operation(
        self,
        request: ObserveRequest,
        candidates: list[dict[str, Any]],
    ) -> dict[str, Any]:
        operation = self._operation(request, candidates)
        self.traces.append(
            ProviderTrace(
                provider_name="deterministic-v4-memory",
                model_id="deterministic-memory",
                provider_role="memory_decision",
                request_purpose="extract_classify_and_judge_memory_lifecycle",
                input_item_count=1 + len(candidates),
                input_token_estimate=max(1, len(request.text) // 4),
                output_item_count=1,
                request_id=f"diag-memory-{len(self.traces) + 1}",
            )
        )
        return operation

    def _operation(
        self,
        request: ObserveRequest,
        candidates: list[dict[str, Any]],
    ) -> dict[str, Any]:
        text = request.text.lower().replace("-", " ")
        if "dependenc" in text and any(
            phrase in text
            for phrase in (
                "avoid adding",
                "do not add",
                "no new",
                "already present",
            )
        ):
            return _write(
                memory_type="preference",
                subject="dependency_policy",
                text=request.text,
                scope_level="project",
                component=None,
            )
        if "jit" in text and "crash" in text:
            prior_index = _candidate_index(candidates, "primary_policy")
            return _write(
                memory_type="decision",
                subject="primary_policy",
                text=request.text,
                scope_level="component",
                component=self._component,
                supersedes=[] if prior_index is None else [prior_index],
            )
        if "package" in text and (
            "interactive" in text
            or "slash command" in text
            or any(command in text.split() for command in ("init", "dev", "deploy"))
        ):
            subject = (
                "interactive_package_policy"
                if "interactive" in text or "slash command" in text
                else "deployment_package_policy"
            )
            prior_index = _candidate_index(candidates, subject)
            return _write(
                memory_type="decision",
                subject=subject,
                text=request.text,
                scope_level="component",
                component=self._component,
                supersedes=[] if prior_index is None else [prior_index],
            )
        if "kuzu" in text and ("backend" in text or "compatibility" in text):
            subject = (
                "legacy_backend_compatibility"
                if text.startswith("existing compatibility")
                or "compatibility tests" in text
                else "new_backend_policy"
            )
            prior_index = _candidate_index(candidates, subject)
            return _write(
                memory_type="decision",
                subject=subject,
                text=request.text,
                scope_level="component",
                component=self._component,
                supersedes=[] if prior_index is None else [prior_index],
            )
        return _no_op("diagnostic_text_did_not_express_durable_memory")


def execute_v4_diagnostic_variants(
    *,
    scenario_root: str | Path,
    fixture_root: str | Path,
) -> V4DiagnosticScenarioResult:
    scenario_path = Path(scenario_root)
    events, scenario_id, evidence_bindings = _load_model_visible_events(scenario_path)
    memory_events = events[:-1]
    goal = events[-1]["summary"]
    downstream_fixture = _load_downstream_fixture(Path(fixture_root), goal)
    raw_candidates = [_context_from_event(event) for event in memory_events]
    input_source_refs = [item["source_ref"] for item in raw_candidates]
    timestamps = {
        event["source_ref"]: event["observed_at"] for event in memory_events
    }

    raw = _run_variant(
        variant_id="raw_full_history",
        selected=raw_candidates,
        fixture=downstream_fixture,
        retrieval_traces=[],
        budget_comparable=False,
        execution_trace={
            "selection_source": "raw_full_history_unfiltered",
            "candidate_count": len(raw_candidates),
            "input_source_refs": input_source_refs,
        },
    )

    semantic_ranked, semantic_traces, semantic_trace = _semantic_rank(
        downstream_fixture.gold["goal"], raw_candidates
    )
    semantic = _run_variant(
        variant_id="semantic_rerank",
        selected=_budgeted_candidates(semantic_ranked),
        fixture=downstream_fixture,
        retrieval_traces=semantic_traces,
        budget_comparable=True,
        execution_trace=semantic_trace,
    )

    recency_ranked, recency_traces, recency_trace = _semantic_rank(
        downstream_fixture.gold["goal"], raw_candidates
    )
    rerank_positions = {
        item["source_ref"]: index for index, item in enumerate(recency_ranked)
    }
    recency_ranked.sort(
        key=lambda item: (
            -_timestamp_key(timestamps[item["source_ref"]]),
            rerank_positions[item["source_ref"]],
        )
    )
    recency_trace.update(
        {
            "selection_source": "embedding_top_20_then_recency",
            "recency_order": [item["source_ref"] for item in recency_ranked],
        }
    )
    recency = _run_variant(
        variant_id="recency_aware",
        selected=_budgeted_candidates(recency_ranked),
        fixture=downstream_fixture,
        retrieval_traces=recency_traces,
        budget_comparable=True,
        execution_trace=recency_trace,
    )

    resolver_ranked, resolver_traces, resolver_trace = _semantic_rank(
        downstream_fixture.gold["goal"], raw_candidates
    )
    resolved, resolution_traces = _resolve_with_ephemeral_lifecycle(
        memory_events,
        component=str(downstream_fixture.gold["component"]),
        candidate_source_refs={item["source_ref"] for item in resolver_ranked[:20]},
    )
    resolver_traces.extend(resolution_traces)
    resolver_trace.update(
        {
            "selection_source": "recall_time_conflict_resolution",
            "resolved_sources": [item["source_ref"] for item in resolved],
            "persisted_lifecycle_used": False,
        }
    )
    resolver = _run_variant(
        variant_id="recall_time_resolver",
        selected=_budgeted_candidates(resolved),
        fixture=downstream_fixture,
        retrieval_traces=resolver_traces,
        budget_comparable=True,
        execution_trace=resolver_trace,
    )

    recallpack_selected, recallpack_traces, recallpack_trace = _run_recallpack_runtime(
        memory_events,
        scenario_id=scenario_id,
        component=str(downstream_fixture.gold["component"]),
        goal=str(downstream_fixture.gold["goal"]),
    )
    recallpack_trace["input_source_refs"] = input_source_refs
    recallpack = _run_variant(
        variant_id="recallpack",
        selected=recallpack_selected,
        fixture=downstream_fixture,
        retrieval_traces=recallpack_traces,
        budget_comparable=True,
        execution_trace=recallpack_trace,
    )

    variants = {
        "raw_full_history": raw,
        "semantic_rerank": semantic,
        "recency_aware": recency,
        "recall_time_resolver": resolver,
        "recallpack": recallpack,
    }
    return V4DiagnosticScenarioResult(
        scenario_id=scenario_id,
        variants=variants,
        strongest_baseline_variant_id=None,
        strongest_baseline_variant_ids=(),
        strongest_baseline_full_suite_passed=None,
        recallpack_full_suite_passed=None,
        classification="diagnostic_patch_generation_only",
        evidence_status="diagnostic_pending_independent_review",
        evidence_bindings=evidence_bindings,
        limitations=(
            "This is an authored source-backed scenario, not a production trace.",
            "Deterministic providers validate runtime structure, not live Qwen capability.",
            "Downstream outcomes remain unknown until the isolated runner executes.",
            "No superiority claim is enabled before independent evidence review and EDD.",
        ),
    )


def _run_variant(
    *,
    variant_id: str,
    selected: list[dict[str, Any]],
    fixture: _DownstreamFixture,
    retrieval_traces: list[ProviderTrace],
    budget_comparable: bool,
    execution_trace: dict[str, Any],
) -> V4DiagnosticVariantResult:
    selected_source_refs = tuple(_candidate_source_ref(item) for item in selected)
    model_visible_selected = [_model_visible_candidate(item) for item in selected]
    pack = SelectedPack(memories=model_visible_selected)
    context = pack.to_canonical_json()
    token_count = count_canonical_json_tokens(context)
    if budget_comparable and token_count > 512:
        raise ValueError("unequal_comparison_contract: model-visible context exceeds 512")
    patch_provider = DeterministicPolicyPatchProvider(
        provider_name="deterministic-v4-patch"
    )
    downstream = prepare_downstream_patch(
        fixture,
        model_visible_selected,
        variant_id,
        patch_provider=patch_provider,
    )
    patch_traces = [result.trace for result in patch_provider.results]
    generated_files = (
        list(patch_provider.results[-1].files) if patch_provider.results else []
    )
    return V4DiagnosticVariantResult(
        variant_id=variant_id,
        selected_context=model_visible_selected,
        selected_source_refs=selected_source_refs,
        model_visible_context=context,
        model_visible_context_sha256=hashlib.sha256(context.encode("utf-8")).hexdigest(),
        exact_token_count=token_count,
        budget_comparable=budget_comparable,
        provider_traces=[
            trace.to_v4_record() for trace in [*retrieval_traces, *patch_traces]
        ],
        downstream=downstream,
        generated_files=generated_files,
        execution_trace=execution_trace,
    )


def _semantic_rank(
    goal: str,
    candidates: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[ProviderTrace], dict[str, Any]]:
    embedding_provider = DeterministicKeywordEmbeddingProvider(
        provider_name="deterministic-v4-embedding"
    )
    query = embedding_provider.embed_query(goal)
    scored = []
    for index, candidate in enumerate(candidates):
        result = embedding_provider.embed_document(_candidate_document(candidate))
        scored.append(
            (_cosine_similarity(query.embedding, result.embedding), index, candidate)
        )
    scored.sort(key=lambda row: (-row[0], row[1]))
    top_twenty = scored[:20]
    rerank_provider = DeterministicKeywordRerankProvider(
        provider_name="deterministic-v4-rerank"
    )
    rerank = rerank_provider.rerank(
        goal=goal,
        documents=[_candidate_document(row[2]) for row in top_twenty],
        instruct="rank raw session events for a coding-agent handoff",
    )
    ranked = [top_twenty[index][2] for index in rerank.ranked_indexes]
    traces = [*embedding_provider.traces, rerank.trace]
    return ranked, traces, {
        "selection_source": "embedding_top_20_then_rerank",
        "embedding_order": [row[2]["source_ref"] for row in scored],
        "rerank_order": [item["source_ref"] for item in ranked],
        "candidate_count": len(candidates),
        "input_source_refs": [item["source_ref"] for item in candidates],
        "rerank_input_count": len(top_twenty),
    }


def _run_recallpack_runtime(
    events: list[dict[str, Any]],
    *,
    scenario_id: str,
    component: str,
    goal: str,
) -> tuple[list[dict[str, Any]], list[ProviderTrace], dict[str, Any]]:
    components = {"retry", "auth", "cache", "config", component}
    decider = _ScenarioLifecycleDecider(component)
    embedding_provider = DeterministicKeywordEmbeddingProvider(
        provider_name="deterministic-v4-embedding"
    )
    ranker = ProviderRanker(
        DeterministicKeywordRerankProvider(
            provider_name="deterministic-v4-rerank"
        )
    )
    with tempfile.TemporaryDirectory() as tmpdir:
        store = SqliteEventStore(Path(tmpdir) / "v4-scenario.sqlite3")
        runtime = ObserveRuntime(
            store=store,
            decider=decider,
            components=components,
            embedding_provider=embedding_provider,
            turnstile_registry=ProjectTurnstileRegistry(),
        )
        observations: list[dict[str, Any]] = []
        for index, event in enumerate(events, start=1):
            source_session, event_id = event["source_ref"].split(":", 1)
            response = runtime.observe(
                ObserveRequest(
                    project_id=f"v4-{scenario_id}",
                    session_id=source_session,
                    event_id=event_id,
                    sequence_no=index,
                    actor=event["actor"],
                    kind=event["kind"],
                    observed_at=event["observed_at"],
                    text=event["summary"],
                ),
                now=100 + index,
            )
            if response.status_code != 200:
                raise RuntimeError(
                    f"V4 diagnostic observe failed at {event['source_ref']}: "
                    f"{response.status_code}/{response.error}"
                )
            observations.append(
                {
                    "source_ref": event["source_ref"],
                    "operation": str((response.final_result or {}).get("operation")),
                }
            )
        compiled = CompileService(
            store=store,
            ranker=ranker,
            embedding_provider=embedding_provider,
            components=components,
        ).compile(
            CompileRequest(
                project_id=f"v4-{scenario_id}",
                goal=goal,
                component=component,
                budget_tokens=512,
            )
        )
    if compiled.status_code != 200:
        raise RuntimeError(
            f"V4 diagnostic compile failed: {compiled.status_code}/{compiled.error}"
        )
    traces = [*decider.traces, *embedding_provider.traces, *ranker.traces]
    trace = dict(compiled.trace)
    trace.update(
        {
            "selection_source": "persisted_write_time_lifecycle",
            "persisted_lifecycle_used": True,
            "observations": observations,
        }
    )
    return list(compiled.pack.memories), traces, trace


def _load_model_visible_events(
    scenario_root: Path,
) -> tuple[list[dict[str, Any]], str, dict[str, str]]:
    events = [
        json.loads(line)
        for line in (scenario_root / "authored-events.jsonl").read_text().splitlines()
        if line.strip()
    ]
    source_ledger = json.loads((scenario_root / "source-ledger.json").read_text())
    relation_ledger = json.loads(
        (scenario_root / "relation-label-ledger.json").read_text()
    )
    provenance = json.loads((scenario_root / "provenance.json").read_text())
    leakage_review = json.loads((scenario_root / "leakage-review.json").read_text())
    scenario_id = source_ledger.get("scenario_slot")
    if not isinstance(scenario_id, str) or not events:
        raise ValueError("invalid_run_reference: scenario packet is empty")
    entries = source_ledger.get("entries")
    if (
        set(source_ledger) != {"record_type", "scenario_slot", "entries"}
        or source_ledger.get("record_type") != "source_ledger"
        or not isinstance(entries, list)
        or len(entries) != len(events)
    ):
        raise ValueError("invalid_run_reference: source ledger does not close events")
    seen: set[str] = set()
    for event, entry in zip(events, entries):
        if (
            not isinstance(event, dict)
            or set(event) != _EVENT_FIELDS
            or event.get("model_visible") is not True
            or event.get("authored_summary") is not True
            or event.get("actor") not in {"user", "assistant", "tool"}
            or event.get("kind") not in {"message", "test_result", "command_result"}
            or not isinstance(entry, dict)
            or set(entry) != {"source_ref", "event_sha256", "model_visible"}
            or entry.get("source_ref") != event.get("source_ref")
            or entry.get("model_visible") is not True
            or entry.get("event_sha256")
            != hashlib.sha256(_canonical_bytes(event)).hexdigest()
            or event.get("source_ref") in seen
        ):
            raise ValueError("invalid_run_reference: source event hash binding failed")
        seen.add(event["source_ref"])
    source_ledger_sha256 = _canonical_sha256(source_ledger)
    relation_entries = relation_ledger.get("entries")
    opportunity_ids = (
        [entry.get("opportunity_id") for entry in relation_entries]
        if isinstance(relation_entries, list)
        else []
    )
    relation_shape_valid = (
        set(relation_ledger)
        == {"record_type", "scenario_slot", "source_ledger_sha256", "entries"}
        and relation_ledger.get("record_type") == "relation_label_ledger"
        and isinstance(relation_entries, list)
        and all(
            isinstance(entry, dict)
            and set(entry)
            == {
                "opportunity_id",
                "prior_source_ref",
                "candidate_source_ref",
                "relation_kind",
            }
            and entry.get("prior_source_ref") in seen
            and entry.get("candidate_source_ref") in seen
            and entry.get("prior_source_ref") != entry.get("candidate_source_ref")
            and isinstance(entry.get("opportunity_id"), str)
            and bool(entry.get("opportunity_id"))
            and entry.get("relation_kind") in {"true_supersession", "hard_negative"}
            for entry in relation_entries
        )
        and len(opportunity_ids) == len(set(opportunity_ids))
    )
    if (
        not relation_shape_valid
        or
        relation_ledger.get("scenario_slot") != scenario_id
        or relation_ledger.get("source_ledger_sha256") != source_ledger_sha256
        or not _valid_provenance(provenance, scenario_id)
        or not _valid_leakage_review(leakage_review, scenario_id)
        or "handoff task" not in str(events[-1].get("summary", "")).lower()
    ):
        raise ValueError("invalid_run_reference: scenario evidence packet is not closed")
    bindings = {
        "source_ledger": source_ledger_sha256,
        "relation_label_ledger": _canonical_sha256(relation_ledger),
        "provenance": _canonical_sha256(provenance),
        "leakage_review": _canonical_sha256(leakage_review),
    }
    bindings["scenario_packet"] = _canonical_sha256(bindings)
    return events, scenario_id, bindings


def _valid_provenance(value: Any, scenario_id: str) -> bool:
    expected_fields = {
        "record_type",
        "scenario_slot",
        "evidence_class",
        "production_trace",
        "copied_source_text",
        "authored_summaries",
        "repository_url",
        "source_urls",
        "commit_refs",
        "license_id",
        "license_status",
        "review_status",
        "limitations",
    }
    if not isinstance(value, dict) or set(value) != expected_fields:
        return False
    source_urls = value.get("source_urls")
    commit_refs = value.get("commit_refs")
    limitations = value.get("limitations")
    return (
        value.get("record_type") == "scenario_provenance"
        and value.get("scenario_slot") == scenario_id
        and value.get("evidence_class") == "source_backed_synthetic"
        and value.get("production_trace") is False
        and value.get("copied_source_text") is False
        and value.get("authored_summaries") is True
        and _https_url(value.get("repository_url"))
        and _nonempty_unique_text_list(source_urls)
        and all(_https_url(url) for url in source_urls)
        and _nonempty_unique_text_list(commit_refs)
        and isinstance(value.get("license_id"), str)
        and bool(value.get("license_id"))
        and value.get("license_status")
        in {
            "verified_from_repository_license",
            "not_asserted_source_inspiration_only",
        }
        and value.get("review_status") == "pending_independent_evidence_review"
        and _nonempty_text_list(limitations)
    )


def _valid_leakage_review(value: Any, scenario_id: str) -> bool:
    expected_fields = {
        "record_type",
        "scenario_slot",
        "review_status",
        "checks",
        "excluded_from_model",
        "verdict",
        "limitations",
    }
    if not isinstance(value, dict) or set(value) != expected_fields:
        return False
    checks = value.get("checks")
    expected_checks = {
        "copied_source_text": False,
        "hidden_test_text_model_visible": False,
        "gold_source_ids_model_visible": False,
        "relation_labels_model_visible": False,
    }
    excluded = value.get("excluded_from_model")
    return (
        value.get("record_type") == "leakage_review"
        and value.get("scenario_slot") == scenario_id
        and value.get("review_status") == "pending_independent_evidence_review"
        and checks == expected_checks
        and _nonempty_unique_text_list(excluded)
        and set(excluded)
        == {
            "relation-label-ledger.json",
            "required source labels",
            "stale source labels",
            "hidden tests",
        }
        and value.get("verdict") == "diagnostic_only_until_external_review"
        and _nonempty_text_list(value.get("limitations"))
    )


def _https_url(value: Any) -> bool:
    return isinstance(value, str) and value.startswith("https://")


def _nonempty_text_list(value: Any) -> bool:
    return (
        isinstance(value, list)
        and bool(value)
        and all(isinstance(item, str) and bool(item) for item in value)
    )


def _nonempty_unique_text_list(value: Any) -> bool:
    return _nonempty_text_list(value) and len(value) == len(set(value))


def _load_downstream_fixture(root: Path, goal: str) -> _DownstreamFixture:
    gold = json.loads((root / "gold.json").read_text())
    required = {"component", "allowed_edit_paths", "hidden_tests"}
    if not required.issubset(gold) or not (root / "repo_snapshot").is_dir():
        raise ValueError("invalid_run_reference: downstream fixture is incomplete")
    fixture_gold = dict(gold)
    fixture_gold["goal"] = goal
    return _DownstreamFixture(root=root, gold=fixture_gold)


def _context_from_event(event: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "id": str(event["source_ref"]).replace(":", "_"),
        "type": "raw_event",
        "subject": "session_event",
        "scope": "raw_history",
        "text": str(event["summary"]),
        "actor": str(event["actor"]),
        "kind": str(event["kind"]),
        "source_ref": str(event["source_ref"]),
    }


def _candidate_source_ref(candidate: Mapping[str, Any]) -> str:
    source_ref = candidate.get("source_ref")
    if not isinstance(source_ref, str) or not source_ref:
        raise ValueError("invalid_run_reference: selected candidate lacks provenance")
    return source_ref


def _model_visible_candidate(candidate: Mapping[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in candidate.items()
        if key not in {"id", "source_ref"}
    }


def _candidate_document(candidate: Mapping[str, Any]) -> str:
    return (
        f"type={candidate['type']}\n"
        f"scope={candidate['scope']}\n"
        f"actor={candidate['actor']}\n"
        f"kind={candidate['kind']}\n"
        f"text={candidate['text']}"
    )


def _resolve_with_ephemeral_lifecycle(
    events: list[dict[str, Any]],
    *,
    component: str,
    candidate_source_refs: set[str],
) -> tuple[list[dict[str, Any]], list[ProviderTrace]]:
    decider = _ScenarioLifecycleDecider(component)
    active: list[dict[str, Any]] = []
    for event in events:
        if event["source_ref"] not in candidate_source_refs:
            continue
        candidates = [
            {
                "candidate_index": index,
                "subject": item["subject"],
                "text": item["text"],
            }
            for index, item in enumerate(active)
        ]
        _session_id, event_id = event["source_ref"].split(":", 1)
        operation = decider.decide_memory_operation(
            ObserveRequest(
                project_id="v4-ephemeral-resolver",
                session_id="recall-time",
                event_id=event_id,
                sequence_no=len(candidates) + 1,
                actor=event["actor"],
                kind=event["kind"],
                observed_at=event["observed_at"],
                text=event["summary"],
            ),
            candidates,
        )
        if operation["operation"] != "write":
            continue
        superseded = set(operation["supersedes_candidate_indexes"])
        active = [
            item for index, item in enumerate(active) if index not in superseded
        ]
        memory = operation["memory"]
        context = _context_from_event(event)
        context.update(
            {
                "type": memory["type"],
                "subject": memory["subject"],
                "scope": memory["scope_level"],
            }
        )
        active.append(context)
    return active, decider.traces


def _budgeted_candidates(candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return list(BudgetSelector(512).select(candidates).memories)


def _timestamp_key(value: str) -> int:
    digits = "".join(character for character in value if character.isdigit())
    if len(digits) != 14:
        raise ValueError("invalid_run_reference: observed_at must be canonical UTC")
    return int(digits)


def _cosine_similarity(left: list[float], right: list[float]) -> float:
    left_norm = math.sqrt(sum(value * value for value in left))
    right_norm = math.sqrt(sum(value * value for value in right))
    if left_norm == 0.0 or right_norm == 0.0:
        return 0.0
    return sum(a * b for a, b in zip(left, right)) / (left_norm * right_norm)


def _candidate_index(
    candidates: list[dict[str, Any]],
    subject: str,
) -> int | None:
    for candidate in candidates:
        if candidate.get("subject") == subject:
            value = candidate.get("candidate_index")
            return value if isinstance(value, int) and not isinstance(value, bool) else None
    return None


def _write(
    *,
    memory_type: str,
    subject: str,
    text: str,
    scope_level: str,
    component: str | None,
    supersedes: list[int] | None = None,
) -> dict[str, Any]:
    return {
        "operation": "write",
        "memory": {
            "type": memory_type,
            "subject": subject,
            "text": text,
            "scope_level": scope_level,
            "component": component,
        },
        "duplicate_of_candidate_index": None,
        "supersedes_candidate_indexes": supersedes or [],
        "reason": "deterministic_v4_diagnostic_lifecycle",
    }


def _no_op(reason: str) -> dict[str, Any]:
    return {
        "operation": "no_op",
        "memory": None,
        "duplicate_of_candidate_index": None,
        "supersedes_candidate_indexes": [],
        "reason": reason,
    }


def _select_strongest_baseline_ids(
    variants: Mapping[str, V4DiagnosticVariantResult],
) -> tuple[str, ...]:
    outcomes = {
        variant_id: _full_suite_passed(variants[variant_id])
        for variant_id in _COMPARATOR_IDS
    }
    strongest_outcome = max(outcomes.values())
    return tuple(
        variant_id
        for variant_id in _COMPARATOR_IDS
        if outcomes[variant_id] is strongest_outcome
    )


def _full_suite_passed(result: V4DiagnosticVariantResult) -> bool:
    summary = result.downstream.get("summary")
    return (
        isinstance(summary, Mapping)
        and summary.get("failed") == 0
        and isinstance(summary.get("passed"), int)
        and summary["passed"] > 0
    )


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _canonical_sha256(value: Any) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()
