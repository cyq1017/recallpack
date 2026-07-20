from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Any

from recallpack.budget import BudgetSelector, BudgetTooSmallError, SelectedPack
from recallpack.memory import MemoryRecord
from recallpack.providers import (
    DeterministicKeywordEmbeddingProvider,
    sanitized_provider_trace_records,
)
from recallpack.tokenization import TokenizerUnavailableError
from recallpack.write_candidates import (
    cosine_similarity,
    validated_query_vector,
    validated_stored_vector,
)


EMBEDDING_TOP_N = 20


@dataclass(frozen=True)
class CompileRequest:
    project_id: str
    goal: str
    component: str
    budget_tokens: int = 512


@dataclass(frozen=True)
class CompileResult:
    status_code: int
    pack: SelectedPack
    trace: dict[str, Any]
    error: str | None = None


class CompileService:
    def __init__(
        self,
        store: object,
        ranker: object,
        embedding_provider: object | None = None,
        retrieval_top_n: int = EMBEDDING_TOP_N,
        components: set[str] | None = None,
    ) -> None:
        self._store = store
        self._ranker = ranker
        self._embedding_provider = (
            embedding_provider
            if embedding_provider is not None
            else DeterministicKeywordEmbeddingProvider()
        )
        # Keep the legacy constructor argument source-compatible while enforcing
        # the frozen V4 compile boundary.
        self._retrieval_top_n = EMBEDDING_TOP_N
        self._components = components or {"retry", "auth", "cache", "config"}

    def compile(self, request: CompileRequest) -> CompileResult:
        if request.component not in self._components:
            return CompileResult(
                status_code=422,
                pack=SelectedPack(memories=[]),
                trace={},
                error="invalid_component",
            )
        if request.budget_tokens < 1 or request.budget_tokens > 512:
            return CompileResult(
                status_code=400,
                pack=SelectedPack(memories=[]),
                trace={},
                error="invalid_budget",
            )

        try:
            candidates, memory_snapshot_seq = self._load_candidates(request)
            base_trace = _base_trace(
                candidate_count=len(candidates),
                memory_snapshot_seq=memory_snapshot_seq,
            )
            retrieval = self._retrieve(request, candidates, base_trace)
            ranked, trace = self._rerank(request, candidates, retrieval, base_trace)
            pack = self._select_pack(request, ranked, trace)
        except _CompileFailure as failure:
            return _error_result(
                failure.error,
                status_code=failure.status_code,
                trace=failure.trace,
            )

        selected_ids = {memory["id"] for memory in pack.memories}
        omissions = [
            {
                "memory_id": memory.id,
                "stage": "embedding",
                "reason": "outside_top_20",
            }
            for memory in retrieval.omitted
        ] + [
            {
                "memory_id": memory.id,
                "stage": "budget",
                "reason": "budget_overflow",
            }
            for memory in ranked
            if memory.id not in selected_ids
        ]
        trace.update(
            {
                "selected_count": len(pack.memories),
                "omitted_count": len(omissions),
                "omissions": omissions,
                "omitted_memory_ids": [
                    omission["memory_id"] for omission in omissions
                ],
            }
        )
        return CompileResult(status_code=200, pack=pack, trace=trace)

    def _load_candidates(
        self, request: CompileRequest
    ) -> tuple[list[MemoryRecord], int]:
        try:
            active = list(self._store.active_memories(request.project_id))
            memory_snapshot_seq = max(
                (memory.source_project_event_seq for memory in active),
                default=0,
            )
            candidates = [
                memory
                for memory in active
                if _scope_overlaps(memory, request.component)
            ]
        except Exception as exc:
            raise _CompileFailure("storage_failure") from exc
        return candidates, memory_snapshot_seq

    def _retrieve(
        self,
        request: CompileRequest,
        candidates: list[MemoryRecord],
        base_trace: dict[str, Any],
    ) -> _RetrievalResult:
        try:
            validated_candidates = [
                (memory, validated_stored_vector(memory)) for memory in candidates
            ]
        except Exception as exc:
            raise _CompileFailure(
                "memory_embedding_backfill_required",
                status_code=409,
                trace=base_trace,
            ) from exc
        try:
            retrieval = _embedding_top_n(
                goal=request.goal,
                candidates=validated_candidates,
                embedding_provider=self._embedding_provider,
                retrieval_top_n=self._retrieval_top_n,
            )
            sanitized_provider_trace_records(retrieval.provider_traces)
        except Exception as exc:
            raise _CompileFailure("embedding_failure", trace=base_trace) from exc
        return retrieval

    def _rerank(
        self,
        request: CompileRequest,
        candidates: list[MemoryRecord],
        retrieval: _RetrievalResult,
        base_trace: dict[str, Any],
    ) -> tuple[list[MemoryRecord], dict[str, Any]]:
        try:
            ranker_trace_count = len(getattr(self._ranker, "traces", []))
            ranked = (
                self._ranker.rank(request.goal, retrieval.candidates)
                if retrieval.candidates
                else []
            )
            _validate_ranked_permutation(ranked, retrieval.candidates)
            ranker_traces = list(getattr(self._ranker, "traces", []))[
                ranker_trace_count:
            ]
            rerank_scores = dict(
                getattr(self._ranker, "last_relevance_scores", {})
            )
            _validate_rerank_contract(
                ranked,
                retrieval.candidates,
                rerank_scores,
                ranker_traces,
            )
            trace = _trace_before_budget(
                candidates=candidates,
                retrieval=retrieval,
                ranker_traces=ranker_traces,
                rerank_scores=rerank_scores,
                memory_snapshot_seq=base_trace["memory_snapshot_seq"],
            )
        except Exception as exc:
            error_trace = _retrieval_error_trace(base_trace, retrieval)
            raise _CompileFailure("rerank_failure", trace=error_trace) from exc
        return ranked, trace

    @staticmethod
    def _select_pack(
        request: CompileRequest,
        ranked: list[MemoryRecord],
        trace: dict[str, Any],
    ) -> SelectedPack:
        try:
            return BudgetSelector(max_tokens=request.budget_tokens).select(
                [_to_pack_item(memory) for memory in ranked]
            )
        except BudgetTooSmallError as exc:
            raise _CompileFailure(
                "budget_too_small", status_code=422, trace=trace
            ) from exc
        except TokenizerUnavailableError as exc:
            raise _CompileFailure("tokenizer_unavailable", trace=trace) from exc
        except Exception as exc:
            raise _CompileFailure("tokenizer_unavailable", trace=trace) from exc


class _CompileFailure(Exception):
    def __init__(
        self,
        error: str,
        *,
        status_code: int = 503,
        trace: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(error)
        self.error = error
        self.status_code = status_code
        self.trace = trace


def _scope_overlaps(memory: MemoryRecord, component: str) -> bool:
    return memory.scope_level == "project" or memory.component == component


@dataclass(frozen=True)
class _RetrievalResult:
    candidates: list[MemoryRecord]
    omitted: list[MemoryRecord]
    scores: dict[str, float]
    provider_traces: list[Any]
    mode: str


def _embedding_top_n(
    goal: str,
    candidates: list[tuple[MemoryRecord, list[float]]],
    embedding_provider: object,
    retrieval_top_n: int,
) -> _RetrievalResult:
    if not candidates:
        return _RetrievalResult(
            candidates=[],
            omitted=[],
            scores={},
            provider_traces=[],
            mode="embedding_top_n",
        )

    query_result = embedding_provider.embed_query(goal)
    query = validated_query_vector(query_result.embedding)
    scored = [
        (cosine_similarity(query, document), memory)
        for memory, document in candidates
    ]
    scored.sort(
        key=lambda item: (
            -item[0],
            -item[1].source_project_event_seq,
            item[1].id,
        )
    )
    selected_count = max(0, min(retrieval_top_n, len(scored)))
    selected = [memory for _, memory in scored[:selected_count]]
    omitted = [memory for _, memory in scored[selected_count:]]
    return _RetrievalResult(
        candidates=selected,
        omitted=omitted,
        scores={memory.id: score for score, memory in scored},
        provider_traces=[query_result.trace],
        mode="embedding_top_n",
    )


def _base_trace(candidate_count: int, memory_snapshot_seq: int = 0) -> dict[str, Any]:
    return {
        "memory_snapshot_seq": memory_snapshot_seq,
        "candidate_count": candidate_count,
        "active_candidate_count": candidate_count,
        "retrieval_mode": "embedding_top_n",
        "embedding_top_n": EMBEDDING_TOP_N,
        "embedding_top_n_count": 0,
        "rerank_input_count": 0,
        "selected_count": 0,
        "omitted_count": 0,
        "omissions": [],
        "candidate_scores": [],
        "reranked_memory_ids": [],
        "artifact_provider_traces": [],
        "provider_mode": "fake",
        "provider_traces": [],
    }


def _trace_before_budget(
    candidates: list[MemoryRecord],
    retrieval: _RetrievalResult,
    ranker_traces: list[Any],
    rerank_scores: dict[str, float],
    memory_snapshot_seq: int,
) -> dict[str, Any]:
    provider_traces = sanitized_provider_trace_records(
        retrieval.provider_traces + ranker_traces
    )
    trace = _base_trace(
        candidate_count=len(candidates),
        memory_snapshot_seq=memory_snapshot_seq,
    )
    trace.update(
        {
            "retrieval_mode": retrieval.mode,
            "embedding_top_n_count": len(retrieval.candidates),
            "rerank_input_count": len(retrieval.candidates),
            "retrieved_memory_ids": [memory.id for memory in retrieval.candidates],
            "omitted_by_embedding_memory_ids": [
                memory.id for memory in retrieval.omitted
            ],
            "provider_mode": (
                "live" if any(item["is_live"] for item in provider_traces) else "fake"
            ),
            "provider_traces": provider_traces,
            "artifact_provider_traces": [
                provider_trace.to_v4_record()
                for provider_trace in retrieval.provider_traces + ranker_traces
            ],
            "candidate_scores": [
                {
                    "memory_id": memory.id,
                    "candidate_index": index,
                    "embedding_cosine": retrieval.scores[memory.id],
                    "rerank_score": rerank_scores.get(memory.id),
                    "source_project_event_seq": memory.source_project_event_seq,
                    "lifecycle_status": "active",
                    "scope": _scope(memory),
                    "source_ref": (
                        f"{memory.source_ref.session_id}:"
                        f"{memory.source_ref.event_id}"
                    ),
                }
                for index, memory in enumerate(retrieval.candidates)
            ],
            "reranked_memory_ids": [
                memory_id
                for memory_id, _ in sorted(
                    rerank_scores.items(),
                    key=lambda item: (
                        -item[1],
                        -next(
                            memory.source_project_event_seq
                            for memory in retrieval.candidates
                            if memory.id == item[0]
                        ),
                        item[0],
                    ),
                )
            ],
        }
    )
    return trace


def _retrieval_error_trace(
    base_trace: dict[str, Any],
    retrieval: _RetrievalResult,
) -> dict[str, Any]:
    trace = dict(base_trace)
    provider_traces = sanitized_provider_trace_records(retrieval.provider_traces)
    trace.update(
        {
            "embedding_top_n_count": len(retrieval.candidates),
            "rerank_input_count": len(retrieval.candidates),
            "retrieved_memory_ids": [memory.id for memory in retrieval.candidates],
            "omitted_by_embedding_memory_ids": [
                memory.id for memory in retrieval.omitted
            ],
            "provider_mode": (
                "live" if any(item["is_live"] for item in provider_traces) else "fake"
            ),
            "provider_traces": provider_traces,
        }
    )
    return trace


def _validate_ranked_permutation(
    ranked: object,
    candidates: list[MemoryRecord],
) -> None:
    if not isinstance(ranked, list):
        raise ValueError("rerank_failure")
    ranked_ids = [getattr(memory, "id", None) for memory in ranked]
    candidate_ids = [memory.id for memory in candidates]
    if len(ranked_ids) != len(candidate_ids) or sorted(ranked_ids) != sorted(candidate_ids):
        raise ValueError("rerank_failure")


def _validate_rerank_contract(
    ranked: list[MemoryRecord],
    candidates: list[MemoryRecord],
    scores: dict[str, object],
    traces: list[object],
) -> None:
    if not candidates:
        if scores or traces:
            raise ValueError("rerank_failure")
        return
    candidate_ids = {memory.id for memory in candidates}
    if set(scores) != candidate_ids:
        raise ValueError("rerank_failure")
    if any(
        isinstance(score, bool)
        or not isinstance(score, (int, float))
        or not math.isfinite(float(score))
        for score in scores.values()
    ):
        raise ValueError("rerank_failure")
    if len(traces) != 1 or getattr(traces[0], "provider_role", None) != "rerank":
        raise ValueError("rerank_failure")
    expected = sorted(
        candidates,
        key=lambda memory: (
            -float(scores[memory.id]),
            -memory.source_project_event_seq,
            memory.id,
        ),
    )
    if [memory.id for memory in ranked] != [memory.id for memory in expected]:
        raise ValueError("rerank_failure")


def _error_result(
    error: str,
    *,
    status_code: int = 503,
    trace: dict[str, Any] | None = None,
) -> CompileResult:
    error_trace = dict(trace or _base_trace(candidate_count=0))
    error_trace["artifacts_published"] = False
    return CompileResult(
        status_code=status_code,
        pack=SelectedPack(memories=[]),
        trace=error_trace,
        error=error,
    )


def _to_pack_item(memory: MemoryRecord) -> dict[str, Any]:
    return {
        "id": memory.id,
        "type": memory.type,
        "subject": memory.subject,
        "text": memory.text,
        "scope": _scope(memory),
        "source_ref": f"{memory.source_ref.session_id}:{memory.source_ref.event_id}",
    }


def _scope(memory: MemoryRecord) -> str:
    if memory.scope_level == "project":
        return "project"
    return f"component:{memory.component}"
