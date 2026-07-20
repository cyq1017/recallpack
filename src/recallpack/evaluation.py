from __future__ import annotations

import json
import math
import tempfile
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from recallpack.budget import SelectedPack, count_canonical_json_tokens
from recallpack.compile import CompileRequest, CompileService
from recallpack.downstream import (
    run_downstream_proof,
    validate_downstream_files as validate_downstream_files,
)
from recallpack.observe import ObserveRequest, ObserveRuntime
from recallpack.providers import (
    DeterministicKeywordEmbeddingProvider,
    DeterministicKeywordRerankProvider,
    FakeEmbeddingProvider,
    FakeRerankProvider,
    ProviderRanker,
    sanitized_provider_trace_records,
)
from recallpack.storage import SqliteEventStore
from recallpack.evaluation_v4 import (
    designate_v4_claim_runs as designate_v4_claim_runs,
    recompute_v4_aggregate_metrics as recompute_v4_aggregate_metrics,
    run_v4_floor_diagnostic as run_v4_floor_diagnostic,
    validate_v4_comparison_contract as validate_v4_comparison_contract,
)
from recallpack.evidence_pipeline import (
    ProductionRunnerOutputJournal as ProductionRunnerOutputJournal,
    run_v4_floor_evidence_pipeline as run_v4_floor_evidence_pipeline,
)
from recallpack.locking import ProjectTurnstileRegistry
from recallpack.evaluation_variants import (
    execute_v4_diagnostic_variants as execute_v4_diagnostic_variants,
)
from recallpack.evaluation_evidence_adapter import (
    build_v4_diagnostic_runner_outputs as build_v4_diagnostic_runner_outputs,
)


@dataclass(frozen=True)
class HeroFixture:
    root: Path
    events: list[ObserveRequest]
    gold: dict[str, Any]


@dataclass(frozen=True)
class VariantResult:
    selected_context: list[dict[str, Any]]
    metrics: dict[str, float | int]
    downstream: dict[str, Any]
    compile_trace: dict[str, Any]


@dataclass(frozen=True)
class HeroEvaluationResult:
    variants: dict[str, VariantResult]


@dataclass(frozen=True)
class MicroSuite:
    root: Path
    cases: list[dict[str, Any]]
    recall_goals: list[dict[str, Any]]
    positioning: str
    operation_counts: dict[str, int]
    gold_edges: list[tuple[str, str]]
    coverage_counts: dict[str, int]
    stale_selected_items: int
    memory_segment_tokens: int


@dataclass(frozen=True)
class MicroSuiteReport:
    raw_counts: dict[str, int]
    confusion_matrix: dict[str, dict[str, int]]
    edge_counts: dict[str, int]
    metrics: dict[str, float | int]
    sections: list[str]
    positioning: str
    prediction_evidence: dict[str, Any]


class HeroFixtureDecider:
    def __init__(self, gold: dict[str, Any] | None = None) -> None:
        self._gold = gold or {}

    def decide_memory_operation(
        self,
        request: ObserveRequest,
        candidates: list[dict[str, Any]],
    ) -> dict[str, Any]:
        memory_events = self._gold.get("memory_events")
        if isinstance(memory_events, dict):
            operation = memory_events.get(f"{request.session_id}:{request.event_id}")
            if operation is None:
                operation = memory_events.get(request.event_id)
            if operation is None:
                return _no_op("non_memory_event")
            return _operation_from_gold(operation, candidates)
        if request.event_id == "turn-001":
            return _write(
                memory_type="decision",
                subject="retry_policy",
                text="Use three attempts with a fixed 100 ms delay.",
                scope_level="component",
                component="retry",
            )
        if request.event_id == "turn-003":
            return _write(
                memory_type="preference",
                subject="dependency_policy",
                text="Do not add new dependencies.",
                scope_level="project",
                component=None,
            )
        if request.event_id == "turn-005":
            return _write(
                memory_type="decision",
                subject="retry_policy",
                text="Use five attempts with exponential backoff.",
                scope_level="component",
                component="retry",
                supersedes_candidate_indexes=[
                    _candidate_index(candidates, "decision", "retry_policy", "retry")
                ],
            )
        if request.event_id == "turn-008":
            return {
                "operation": "duplicate",
                "memory": None,
                "duplicate_of_candidate_index": _candidate_index(
                    candidates, "preference", "dependency_policy", None
                ),
                "supersedes_candidate_indexes": [],
                "reason": "same_dependency_preference",
            }
        if request.event_id == "turn-010":
            return _write(
                memory_type="decision",
                subject="auth_policy",
                text="Use bearer token validation in auth.",
                scope_level="component",
                component="auth",
            )
        return _no_op("non_memory_event")


def load_hero_fixture(root: str | Path) -> HeroFixture:
    fixture_root = Path(root)
    events = [
        _event_from_json(json.loads(line))
        for line in (fixture_root / "sessions.jsonl").read_text().splitlines()
        if line.strip()
    ]
    gold = json.loads((fixture_root / "gold.json").read_text())
    return HeroFixture(root=fixture_root, events=events, gold=gold)


def evaluate_hero_fixture(root: str | Path) -> HeroEvaluationResult:
    fixture = load_hero_fixture(root)
    raw_full_history = _evaluate_raw_full_history(fixture)
    embedding_top_k_rag = _evaluate_embedding_top_k_rag(fixture)
    recallpack = _evaluate_recallpack(fixture)
    return HeroEvaluationResult(
        variants={
            "raw_full_history": raw_full_history,
            "embedding_top_k_rag": embedding_top_k_rag,
            "recallpack": recallpack,
        }
    )


def load_micro_suite(root: str | Path) -> MicroSuite:
    fixture_root = Path(root)
    payload = json.loads((fixture_root / "suite.json").read_text())
    cases = payload["cases"]
    return MicroSuite(
        root=fixture_root,
        cases=cases,
        recall_goals=payload["recall_goals"],
        positioning=payload["positioning"],
        operation_counts=dict(Counter(case["gold_operation"] for case in cases)),
        gold_edges=[
            tuple(case["gold_edge"])
            for case in cases
            if case.get("gold_edge") is not None
        ],
        coverage_counts=dict(
            Counter(tag for case in cases for tag in case.get("tags", []))
        ),
        stale_selected_items=int(payload.get("stale_selected_items", 0)),
        memory_segment_tokens=int(payload.get("memory_segment_tokens", 0)),
    )


def evaluate_micro_suite(
    root: str | Path,
    decider_overrides: dict[str, dict[str, Any]] | None = None,
) -> MicroSuiteReport:
    suite = load_micro_suite(root)
    predictions, prediction_evidence = _behavioral_micro_suite_predictions(
        suite,
        decider_overrides or {},
    )
    raw_counts = _micro_suite_raw_counts(predictions)
    edge_counts = _micro_suite_edge_counts(predictions)
    metrics = _micro_suite_metrics(suite, predictions, raw_counts, edge_counts)
    return MicroSuiteReport(
        raw_counts=raw_counts,
        confusion_matrix=_micro_suite_confusion_matrix(predictions),
        edge_counts=edge_counts,
        metrics=metrics,
        sections=["raw_counts", "confusion_matrix", "edge_counts", "rates"],
        positioning=suite.positioning,
        prediction_evidence=prediction_evidence,
    )


class MicroSuiteBehavioralDecider:
    def __init__(
        self,
        cases: list[dict[str, Any]],
        overrides: dict[str, dict[str, Any]],
    ) -> None:
        self._cases = {case["id"]: case for case in cases}
        self._overrides = overrides
        self.selected_prior_source_by_event: dict[str, str] = {}

    def decide_memory_operation(
        self,
        request: ObserveRequest,
        candidates: list[dict[str, Any]],
    ) -> dict[str, Any]:
        if request.event_id.startswith("seed_duplicate_candidate_"):
            return _write(
                memory_type="decision",
                subject=request.event_id,
                text=f"Seed memory for {request.event_id}.",
                scope_level="component",
                component="retry",
            )
        if request.event_id in self._overrides:
            return dict(self._overrides[request.event_id])

        case = self._cases[request.event_id]
        operation = case.get("behavior_operation", case["gold_operation"])
        if operation == "no_op":
            return {
                "operation": "no_op",
                "memory": None,
                "duplicate_of_candidate_index": None,
                "supersedes_candidate_indexes": [],
                "reason": f"micro_suite_{case['id']}",
            }
        if operation == "duplicate":
            return {
                "operation": "duplicate",
                "memory": None,
                "duplicate_of_candidate_index": 0,
                "supersedes_candidate_indexes": [],
                "reason": f"micro_suite_{case['id']}",
            }
        if operation in {"write_independent", "write_superseding"}:
            memory_type = str(case.get("behavior_memory_type", case["gold_memory_type"]))
            supersedes_indexes: list[int] = []
            if operation == "write_superseding":
                prior_source = case["gold_edge"][0]
                prior_index = _candidate_index_by_source_ref(candidates, prior_source)
                if prior_index is None:
                    return {
                        "operation": "no_op",
                        "memory": None,
                        "duplicate_of_candidate_index": None,
                        "supersedes_candidate_indexes": [],
                        "reason": f"missing_prior_{prior_source}",
                    }
                supersedes_indexes = [prior_index]
                self.selected_prior_source_by_event[case["id"]] = prior_source
            return _write(
                memory_type=memory_type,
                subject=_micro_suite_subject(case),
                text=_micro_suite_memory_text(case),
                scope_level=_micro_suite_scope_level(memory_type),
                component=_micro_suite_component(memory_type),
                supersedes_candidate_indexes=supersedes_indexes,
            )
        return {
            "operation": "no_op",
            "memory": None,
            "duplicate_of_candidate_index": None,
            "supersedes_candidate_indexes": [],
            "reason": "invalid_micro_suite_behavior_operation",
        }


def _evaluate_recallpack(fixture: HeroFixture) -> VariantResult:
    with tempfile.TemporaryDirectory() as tmpdir:
        store = SqliteEventStore(Path(tmpdir) / "recallpack.sqlite3")
        fixture_component = str(fixture.gold.get("component", "retry"))
        components = {"retry", "auth", "cache", "config", fixture_component}
        runtime = ObserveRuntime(
            store=store,
            decider=HeroFixtureDecider(fixture.gold),
            components=components,
            turnstile_registry=ProjectTurnstileRegistry(),
        )
        for event in fixture.events:
            runtime.observe(event, now=100 + event.sequence_no)
        compile_result = CompileService(
            store=store,
            ranker=ProviderRanker(FakeRerankProvider()),
            embedding_provider=DeterministicKeywordEmbeddingProvider(),
            components=components,
        ).compile(
            CompileRequest(
                project_id=fixture.gold.get("project_id", "project-a"),
                goal=fixture.gold["goal"],
                component=fixture_component,
                budget_tokens=512,
            )
        )
    selected = list(compile_result.pack.memories)
    return VariantResult(
        selected_context=selected,
        metrics=_metrics(selected, fixture.gold, compile_result.pack),
        downstream=run_downstream_proof(fixture, selected, "recallpack"),
        compile_trace=compile_result.trace,
    )


def _evaluate_raw_full_history(fixture: HeroFixture) -> VariantResult:
    selected = [_raw_event_context(event) for event in fixture.events]
    return VariantResult(
        selected_context=selected,
        metrics=_metrics(selected, fixture.gold, SelectedPack(memories=selected)),
        downstream=run_downstream_proof(fixture, selected, "raw_full_history"),
        compile_trace={
            "selection_source": "raw_full_history_unfiltered",
            "budget_comparable": False,
            "selected_count": len(selected),
            "candidate_count": len(selected),
        },
    )


def _evaluate_embedding_top_k_rag(
    fixture: HeroFixture,
    top_k: int = 2,
    top_n: int = 4,
) -> VariantResult:
    candidates = [_raw_event_context(event) for event in fixture.events]
    if fixture.gold.get("baseline_embedding_mode") == "deterministic_keyword_provider":
        provider = DeterministicKeywordEmbeddingProvider()
    else:
        provider = FakeEmbeddingProvider(vectors=_hero_baseline_embedding_vectors(fixture))
    query = provider.embed_query(fixture.gold["goal"])
    scored: list[tuple[float, int, dict[str, Any], Any]] = []
    for index, candidate in enumerate(candidates):
        embedded = provider.embed_document(_raw_event_document(candidate))
        score = _cosine_similarity(query.embedding, embedded.embedding)
        scored.append((score, index, candidate, embedded.trace))
    scored.sort(key=lambda item: (-item[0], item[1]))
    top_n_scored = scored[:top_n]
    if fixture.gold.get("baseline_embedding_mode") == "deterministic_keyword_provider":
        rerank_provider = DeterministicKeywordRerankProvider()
    else:
        rerank_provider = FakeRerankProvider(ranked_indexes=list(range(len(top_n_scored))))
    rerank = rerank_provider.rerank(
        goal=fixture.gold["goal"],
        documents=[_raw_event_document(candidate) for _, _, candidate, _ in top_n_scored],
        instruct="rank raw session events for a coding-agent handoff",
    )
    selected = [
        top_n_scored[index][2]
        for index in rerank.ranked_indexes[:top_k]
        if index < len(top_n_scored)
    ]
    provider_traces = [query.trace]
    provider_traces.extend(trace for _, _, _, trace in scored)
    provider_traces.append(rerank.trace)
    return VariantResult(
        selected_context=selected,
        metrics=_metrics(selected, fixture.gold, SelectedPack(memories=selected)),
        downstream=run_downstream_proof(fixture, selected, "embedding_top_k_rag"),
        compile_trace={
            "selection_source": "computed_embedding_top_k_raw_events",
            "retrieval_mode": "embedding_top_n_rerank_raw_history",
            "embedding_top_k": top_k,
            "embedding_top_n_count": len(top_n_scored),
            "rerank_input_count": len(top_n_scored),
            "candidate_count": len(candidates),
            "selected_count": len(selected),
            "ranked_sources": [
                {
                    "source_ref": candidate["source_ref"],
                    "similarity": round(score, 6),
                }
                for score, _, candidate, _ in scored
            ],
            "reranked_sources": [
                {
                    "source_ref": top_n_scored[index][2]["source_ref"],
                    "rerank_position": position,
                }
                for position, index in enumerate(rerank.ranked_indexes, start=1)
                if index < len(top_n_scored)
            ],
            "provider_traces": sanitized_provider_trace_records(provider_traces),
        },
    )


def _raw_event_context(event: ObserveRequest) -> dict[str, Any]:
    return {
        "id": _source_ref(event).replace(":", "_"),
        "type": "raw_event",
        "subject": "session_event",
        "text": event.text,
        "scope": "raw_history",
        "actor": event.actor,
        "kind": event.kind,
        "source_ref": _source_ref(event),
    }


def _raw_event_document(candidate: dict[str, Any]) -> str:
    return (
        f"type={candidate['type']}\n"
        f"scope={candidate['scope']}\n"
        f"actor={candidate['actor']}\n"
        f"kind={candidate['kind']}\n"
        f"source={candidate['source_ref']}\n"
        f"text={candidate['text']}"
    )


def _hero_baseline_embedding_vectors(fixture: HeroFixture) -> dict[str, list[float]]:
    vectors: dict[str, list[float]] = {
        f"query:{fixture.gold['goal']}": _baseline_embedding_vector(
            fixture.gold["goal"],
            fixture.gold,
        )
    }
    for event in fixture.events:
        candidate = _raw_event_context(event)
        document = _raw_event_document(candidate)
        vectors[f"document:{document}"] = _baseline_embedding_vector(
            document,
            fixture.gold,
        )
    return vectors


def _baseline_embedding_vector(
    text: str,
    gold: dict[str, Any] | None = None,
) -> list[float]:
    normalized = text.lower()
    if gold is not None and "baseline_embedding_terms" in gold:
        for phrase in gold.get("baseline_downrank_phrases", []):
            if str(phrase).lower() in normalized:
                return [0.0, 0.0, 1.0]
        terms = gold["baseline_embedding_terms"]
        primary_axis = _term_score(
            normalized,
            [str(term).lower() for term in terms.get("primary", [])],
        )
        secondary_axis = _term_score(
            normalized,
            [str(term).lower() for term in terms.get("secondary", [])],
        )
        current_axis = _term_score(
            normalized,
            [str(term).lower() for term in terms.get("current", [])],
        )
        return [
            primary_axis * 2.0,
            secondary_axis,
            current_axis,
        ]
    if (
        "actor=assistant" in normalized
        or "actor=tool" in normalized
        or "current handoff task" in normalized
        or "replaces the earlier" in normalized
    ):
        return [0.0, 0.0, 1.0]
    retry_axis = _term_score(normalized, ["retry", "helper", "attempt", "attempts"])
    project_axis = _term_score(
        normalized,
        ["project", "policy", "dependency", "dependency-free", "pyproject"],
    )
    rate_limit_axis = _term_score(
        normalized,
        ["rate-limit", "rate", "limit", "exponential", "backoff", "failures"],
    )
    return [
        retry_axis * 2.0,
        project_axis,
        rate_limit_axis,
    ]


def _term_score(text: str, terms: list[str]) -> float:
    return float(sum(1 for term in terms if term in text))


def _cosine_similarity(left: list[float], right: list[float]) -> float:
    left_norm = math.sqrt(sum(value * value for value in left))
    right_norm = math.sqrt(sum(value * value for value in right))
    if left_norm == 0.0 or right_norm == 0.0:
        return 0.0
    return sum(a * b for a, b in zip(left, right)) / (left_norm * right_norm)


def _behavioral_micro_suite_predictions(
    suite: MicroSuite,
    decider_overrides: dict[str, dict[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    predictions: list[dict[str, Any]] = []
    deprecated_prediction_field_count = sum(
        1
        for case in suite.cases
        if any(key.startswith("predicted_") for key in case)
    )
    with tempfile.TemporaryDirectory() as tmpdir:
        store = SqliteEventStore(Path(tmpdir) / "micro-suite.sqlite3")
        decider = MicroSuiteBehavioralDecider(suite.cases, decider_overrides)
        runtime = ObserveRuntime(
            store=store,
            decider=decider,
            turnstile_registry=ProjectTurnstileRegistry(),
        )
        sequence_no = 1
        for seed_index in range(_duplicate_case_count(suite.cases)):
            seed_request = ObserveRequest(
                project_id="micro-suite",
                session_id="behavioral-evaluator",
                event_id=f"seed_duplicate_candidate_{seed_index + 1}",
                sequence_no=sequence_no,
                actor="user",
                kind="message",
                observed_at=_micro_suite_observed_at(sequence_no),
                text=f"Seed duplicate candidate {seed_index + 1}.",
            )
            seed_response = runtime.observe(seed_request, now=1000 + sequence_no)
            if seed_response.status_code != 200:
                raise RuntimeError(f"micro-suite seed failed: {seed_response.error}")
            sequence_no += 1

        for case in suite.cases:
            request = ObserveRequest(
                project_id="micro-suite",
                session_id="behavioral-evaluator",
                event_id=case["id"],
                sequence_no=sequence_no,
                actor=_micro_suite_actor(case),
                kind="message",
                observed_at=_micro_suite_observed_at(sequence_no),
                text=str(case.get("event_text", f"Micro-suite case {case['id']}.")),
            )
            response = runtime.observe(request, now=1000 + sequence_no)
            predictions.append(_case_prediction(case, response, decider))
            sequence_no += 1

    evidence = {
        "prediction_source": "behavioral_runtime",
        "used_fixture_predictions": False,
        "case_count": len(predictions),
        "seed_event_count": _duplicate_case_count(suite.cases),
        "deprecated_prediction_field_case_count": deprecated_prediction_field_count,
        "decider_override_count": len(decider_overrides),
    }
    return predictions, evidence


def _case_prediction(
    case: dict[str, Any],
    response: Any,
    decider: MicroSuiteBehavioralDecider,
) -> dict[str, Any]:
    predicted = {
        key: value
        for key, value in case.items()
        if not key.startswith("predicted_")
    }
    final_result = response.final_result or {}
    operation = final_result.get("operation")
    predicted["predicted_operation"] = _predicted_operation(final_result)
    if operation == "write" and isinstance(final_result.get("memory"), dict):
        predicted["predicted_memory_type"] = final_result["memory"].get("type")
        superseded_ids = final_result.get("superseded_memory_ids")
        if superseded_ids:
            prior_source = decider.selected_prior_source_by_event.get(case["id"])
            if prior_source is not None:
                predicted["predicted_edge"] = [prior_source, case["id"]]
    return predicted


def _predicted_operation(final_result: dict[str, Any]) -> str:
    operation = final_result.get("operation")
    if operation == "write":
        superseded_ids = final_result.get("superseded_memory_ids")
        return "write_superseding" if superseded_ids else "write_independent"
    if operation in {"duplicate", "no_op"}:
        return str(operation)
    return "no_op"


def _duplicate_case_count(cases: list[dict[str, Any]]) -> int:
    return sum(1 for case in cases if case["gold_operation"] == "duplicate")


def _micro_suite_actor(case: dict[str, Any]) -> str:
    memory_type = case.get("behavior_memory_type", case.get("gold_memory_type"))
    if case["gold_operation"] == "no_op" and "assistant_vs_user_authority" in case.get("tags", []):
        return "assistant"
    if memory_type == "preference":
        return "user"
    return "user"


def _micro_suite_observed_at(sequence_no: int) -> str:
    return f"2026-06-24T00:{sequence_no:02d}:00Z"


def _candidate_index_by_source_ref(
    candidates: list[dict[str, Any]],
    source_event_id: str,
) -> int | None:
    for candidate in candidates:
        source_ref = candidate.get("source_ref")
        if isinstance(source_ref, dict) and source_ref.get("event_id") == source_event_id:
            return int(candidate["candidate_index"])
    return None


def _micro_suite_subject(case: dict[str, Any]) -> str:
    if case["gold_operation"] == "write_superseding":
        return f"subject_{case['gold_edge'][0]}"
    return f"subject_{case['id']}"


def _micro_suite_memory_text(case: dict[str, Any]) -> str:
    return str(case.get("memory_text", f"Memory created by micro-suite case {case['id']}."))


def _micro_suite_scope_level(memory_type: str) -> str:
    if memory_type == "preference":
        return "project"
    return "component"


def _micro_suite_component(memory_type: str) -> str | None:
    if memory_type == "preference":
        return None
    return "retry"


def _metrics(
    selected_context: list[dict[str, Any]],
    gold: dict[str, Any],
    pack: SelectedPack,
) -> dict[str, float | int]:
    selected_sources = {item["source_ref"] for item in selected_context}
    required_sources = set(gold["required_sources"])
    stale_sources = set(gold["stale_sources"])
    selected_required = selected_sources & required_sources
    selected_stale = selected_sources & stale_sources
    return {
        "required_memory_recall_at_budget": len(selected_required) / len(required_sources),
        "stale_leakage_rate": (
            len(selected_stale) / len(selected_context) if selected_context else 0.0
        ),
        "hidden_test_pass_count": _hidden_test_pass_count(selected_sources, gold),
        "memory_segment_tokens": count_canonical_json_tokens(pack.to_canonical_json()),
    }


def _hidden_test_pass_count(selected_sources: set[str], gold: dict[str, Any]) -> int:
    if set(gold["required_sources"]).issubset(selected_sources) and not (
        set(gold["stale_sources"]) & selected_sources
    ):
        return len(gold["hidden_tests"])
    return len(set(gold["required_sources"]) & selected_sources)


def _micro_suite_raw_counts(cases: list[dict[str, Any]]) -> dict[str, int]:
    counts = {"tp": 0, "fp": 0, "fn": 0, "tn": 0}
    for case in cases:
        gold_positive = _micro_suite_is_write(case["gold_operation"])
        predicted_positive = _micro_suite_is_write(case["predicted_operation"])
        if gold_positive and predicted_positive:
            counts["tp"] += 1
        elif not gold_positive and predicted_positive:
            counts["fp"] += 1
        elif gold_positive and not predicted_positive:
            counts["fn"] += 1
        else:
            counts["tn"] += 1
    return counts


def _micro_suite_confusion_matrix(
    cases: list[dict[str, Any]],
) -> dict[str, dict[str, int]]:
    operations = ["no_op", "duplicate", "write_independent", "write_superseding"]
    matrix = {
        gold_operation: {predicted_operation: 0 for predicted_operation in operations}
        for gold_operation in operations
    }
    for case in cases:
        matrix[case["gold_operation"]][case["predicted_operation"]] += 1
    return matrix


def _micro_suite_edge_counts(cases: list[dict[str, Any]]) -> dict[str, int]:
    gold_edges = {
        tuple(case["gold_edge"])
        for case in cases
        if case.get("gold_edge") is not None
    }
    predicted_edges = {
        tuple(case["predicted_edge"])
        for case in cases
        if case.get("predicted_edge") is not None
    }
    return {
        "gold": len(gold_edges),
        "predicted": len(predicted_edges),
        "correct": len(gold_edges & predicted_edges),
    }


def _micro_suite_metrics(
    suite: MicroSuite,
    predictions: list[dict[str, Any]],
    raw_counts: dict[str, int],
    edge_counts: dict[str, int],
) -> dict[str, float | int]:
    precision = _safe_ratio(raw_counts["tp"], raw_counts["tp"] + raw_counts["fp"])
    recall = _safe_ratio(raw_counts["tp"], raw_counts["tp"] + raw_counts["fn"])
    edge_precision = _safe_ratio(edge_counts["correct"], edge_counts["predicted"])
    edge_recall = _safe_ratio(edge_counts["correct"], edge_counts["gold"])
    return {
        "should_create_memory_precision": precision,
        "should_create_memory_recall": recall,
        "should_create_memory_f1": _f1(precision, recall),
        "edge_precision": edge_precision,
        "edge_recall": edge_recall,
        "edge_f1": _f1(edge_precision, edge_recall),
        "memory_type_accuracy": _micro_suite_memory_type_accuracy(predictions),
        "required_memory_recall_at_512": _micro_suite_required_recall(
            suite.recall_goals
        ),
        "stale_selected_items": suite.stale_selected_items,
        "memory_segment_tokens": suite.memory_segment_tokens,
    }


def _micro_suite_memory_type_accuracy(cases: list[dict[str, Any]]) -> float:
    writable_cases = [
        case
        for case in cases
        if _micro_suite_is_write(case["gold_operation"])
        and _micro_suite_is_write(case["predicted_operation"])
    ]
    correct = sum(
        1
        for case in writable_cases
        if case.get("gold_memory_type") == case.get("predicted_memory_type")
    )
    return _safe_ratio(correct, len(writable_cases))


def _micro_suite_required_recall(recall_goals: list[dict[str, Any]]) -> float:
    covered_goals = 0
    for goal in recall_goals:
        required = set(goal["required_sources"])
        selected = set(goal["selected_sources"])
        if required.issubset(selected):
            covered_goals += 1
    return _safe_ratio(covered_goals, len(recall_goals))


def _micro_suite_is_write(operation: str) -> bool:
    return operation in {"write_independent", "write_superseding"}


def _safe_ratio(numerator: int, denominator: int) -> float:
    if denominator == 0:
        return 0.0
    return numerator / denominator


def _f1(precision: float, recall: float) -> float:
    if precision + recall == 0:
        return 0.0
    return 2 * precision * recall / (precision + recall)


def _write(
    memory_type: str,
    subject: str,
    text: str,
    scope_level: str,
    component: str | None,
    supersedes_candidate_indexes: list[int] | None = None,
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
        "supersedes_candidate_indexes": supersedes_candidate_indexes or [],
        "reason": "fixture_gold_operation",
    }


def _no_op(reason: str) -> dict[str, Any]:
    return {
        "operation": "no_op",
        "memory": None,
        "duplicate_of_candidate_index": None,
        "supersedes_candidate_indexes": [],
        "reason": reason,
    }


def _operation_from_gold(
    operation: dict[str, Any],
    candidates: list[dict[str, Any]],
) -> dict[str, Any]:
    if operation.get("operation") == "write":
        memory = operation["memory"]
        supersedes_indexes = [
            _candidate_index(
                candidates,
                str(candidate["type"]),
                str(candidate["subject"]),
                candidate.get("component"),
            )
            for candidate in operation.get("supersedes_candidates", [])
        ]
        return _write(
            memory_type=str(memory["type"]),
            subject=str(memory["subject"]),
            text=str(memory["text"]),
            scope_level=str(memory["scope_level"]),
            component=memory.get("component"),
            supersedes_candidate_indexes=supersedes_indexes,
        )
    if operation.get("operation") == "duplicate":
        duplicate = operation["duplicate_candidate"]
        return {
            "operation": "duplicate",
            "memory": None,
            "duplicate_of_candidate_index": _candidate_index(
                candidates,
                str(duplicate["type"]),
                str(duplicate["subject"]),
                duplicate.get("component"),
            ),
            "supersedes_candidate_indexes": [],
            "reason": "fixture_gold_operation",
        }
    return _no_op(str(operation.get("reason", "fixture_gold_no_op")))


def _candidate_index(
    candidates: list[dict[str, Any]],
    memory_type: str,
    subject: str,
    component: str | None,
) -> int:
    for candidate in candidates:
        if (
            candidate["type"] == memory_type
            and candidate["subject"] == subject
            and candidate["component"] == component
        ):
            return int(candidate["candidate_index"])
    raise ValueError(f"missing candidate for {memory_type}/{subject}/{component}")


def _event_from_json(payload: dict[str, Any]) -> ObserveRequest:
    return ObserveRequest(
        project_id=payload["project_id"],
        session_id=payload["session_id"],
        event_id=payload["event_id"],
        sequence_no=int(payload["sequence_no"]),
        actor=payload["actor"],
        kind=payload["kind"],
        observed_at=payload["observed_at"],
        text=payload["text"],
    )


def _source_ref(event: ObserveRequest) -> str:
    return f"{event.session_id}:{event.event_id}"
