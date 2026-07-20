from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from recallpack.downstream import run_downstream_proof
from recallpack.evaluation import (
    _cosine_similarity,
    _raw_event_context,
    _raw_event_document,
    load_hero_fixture,
)
from recallpack.live_qwen_contract import (
    DEFAULT_COMPATIBLE_BASE_URL,
    DEFAULT_RERANK_BASE_URL,
)
from recallpack.providers import (
    QwenCloudHTTPClient,
    QwenEmbeddingProvider,
    QwenRerankProvider,
    ProviderTrace,
    RERANK_MODEL,
    TEXT_EMBEDDING_MODEL,
    sanitized_provider_trace_records,
)


def build_live_qwen_embedding_baseline_preflight_report(
    fixture_root: str | Path,
    compatible_base_url: str = DEFAULT_COMPATIBLE_BASE_URL,
    rerank_base_url: str = DEFAULT_RERANK_BASE_URL,
) -> dict[str, Any]:
    opener = _PreflightOpener(_preflight_success_responses())
    report = build_live_qwen_embedding_baseline_report(
        fixture_root=fixture_root,
        api_key="placeholder",
        compatible_base_url=compatible_base_url,
        rerank_base_url=rerank_base_url,
        opener=opener,
    )
    request_role_counts = _request_role_counts(opener.requests)
    embedding_contract = _embedding_request_contract(opener.requests)
    rerank_contract = _rerank_request_contract(opener.requests)
    checks = {
        "real_embedding_endpoint_contract_ready": (
            request_role_counts.get("embedding") == 13
            and embedding_contract["all_text_embedding_v4"]
            and embedding_contract["query_request_count"] == 1
            and embedding_contract["document_request_count"] == 12
        ),
        "real_rerank_endpoint_contract_ready": (
            request_role_counts.get("rerank") == 1
            and rerank_contract["all_qwen3_rerank"]
            and rerank_contract["all_top_n_matches_document_count"]
            and rerank_contract["all_instruct_present"]
        ),
        "stale_retry_selected_by_real_embedding_path": (
            "session-a:turn-001" in report.get("selected_sources", [])
        ),
        "active_retry_not_selected_by_baseline": (
            "session-a:turn-005" not in report.get("selected_sources", [])
        ),
        "downstream_baseline_fails": report.get("downstream_tests") == {"passed": 1, "failed": 2},
    }
    return {
        "preflight_status": (
            "ready_for_live_embedding_baseline_rerun"
            if all(checks.values())
            else "not_ready_for_live_embedding_baseline_rerun"
        ),
        "live_qwen_run": False,
        "network_calls_made": False,
        "scenario": "hero_real_embedding_raw_history_baseline_preflight",
        "model_names": {"embedding": TEXT_EMBEDDING_MODEL, "rerank": RERANK_MODEL},
        "request_role_counts": request_role_counts,
        "embedding_request_contract": embedding_contract,
        "rerank_request_contract": rerank_contract,
        "retrieval_top_n": report["retrieval_top_n"],
        "selection_top_k": report["selection_top_k"],
        "expected_selected_sources": list(report["selected_sources"]),
        "expected_downstream_tests": _downstream_ratio(report["downstream_tests"]),
        "ranked_sources": list(report["ranked_sources"]),
        "reranked_sources": list(report["reranked_sources"]),
        "checks": checks,
        "actual_qwen_token_usage": report["actual_qwen_token_usage"],
        "next_gated_action": (
            "Rerun live Qwen embedding baseline only after explicit approval; "
            "preflight does not read credentials or call Qwen."
        ),
    }


def write_live_qwen_embedding_baseline_preflight_report(
    target: str | Path,
    fixture_root: str | Path,
    compatible_base_url: str = DEFAULT_COMPATIBLE_BASE_URL,
    rerank_base_url: str = DEFAULT_RERANK_BASE_URL,
) -> dict[str, Any]:
    report = build_live_qwen_embedding_baseline_preflight_report(
        fixture_root=fixture_root,
        compatible_base_url=compatible_base_url,
        rerank_base_url=rerank_base_url,
    )
    _write_json(target, report)
    return report


def build_live_qwen_embedding_baseline_report(
    fixture_root: str | Path,
    api_key: str,
    compatible_base_url: str = DEFAULT_COMPATIBLE_BASE_URL,
    rerank_base_url: str = DEFAULT_RERANK_BASE_URL,
    opener: Any | None = None,
    retrieval_top_n: int = 4,
    selection_top_k: int = 2,
) -> dict[str, Any]:
    fixture = load_hero_fixture(fixture_root)
    client = QwenCloudHTTPClient(api_key=api_key, opener=opener)
    embedding_provider = QwenEmbeddingProvider(
        client=client,
        compatible_base_url=compatible_base_url,
    )
    rerank_provider = QwenRerankProvider(
        client=client,
        rerank_base_url=rerank_base_url,
    )

    candidates = [_raw_event_context(event) for event in fixture.events]
    traces: list[ProviderTrace] = []
    query = embedding_provider.embed_query(fixture.gold["goal"])
    traces.append(query.trace)
    scored: list[tuple[float, int, dict[str, Any], ProviderTrace]] = []
    for index, candidate in enumerate(candidates):
        embedded = embedding_provider.embed_document(_raw_event_document(candidate))
        traces.append(embedded.trace)
        score = _cosine_similarity(query.embedding, embedded.embedding)
        scored.append((score, index, candidate, embedded.trace))

    scored.sort(key=lambda item: (-item[0], item[1]))
    top_n_scored = scored[:retrieval_top_n]
    rerank = rerank_provider.rerank(
        goal=fixture.gold["goal"],
        documents=[_raw_event_document(candidate) for _, _, candidate, _ in top_n_scored],
        instruct="rank raw session events for a coding-agent handoff",
    )
    traces.append(rerank.trace)
    selected = [
        top_n_scored[index][2]
        for index in rerank.ranked_indexes[:selection_top_k]
        if index < len(top_n_scored)
    ]
    downstream = run_downstream_proof(
        fixture,
        selected,
        "live_qwen_embedding_raw_history_baseline",
    )
    selected_sources = [candidate["source_ref"] for candidate in selected]
    checks = {
        "stale_retry_selected": "session-a:turn-001" in selected_sources,
        "active_retry_selected": "session-a:turn-005" in selected_sources,
        "project_preference_selected": "session-a:turn-003" in selected_sources,
        "downstream_baseline_fails": downstream["summary"] == {"passed": 1, "failed": 2},
    }
    live_status = (
        "live_embedding_baseline_passed"
        if checks["stale_retry_selected"]
        and not checks["active_retry_selected"]
        and checks["downstream_baseline_fails"]
        else "live_embedding_baseline_failed"
    )
    return {
        "live_qwen_run": True,
        "live_status": live_status,
        "scenario": "hero_real_embedding_raw_history_baseline",
        "project_id": fixture.gold.get("project_id", "project-a"),
        "region_base_url": compatible_base_url.rstrip("/"),
        "rerank_base_url": rerank_base_url.rstrip("/"),
        "model_names": {"embedding": TEXT_EMBEDDING_MODEL, "rerank": RERANK_MODEL},
        "retrieval_top_n": retrieval_top_n,
        "selection_top_k": selection_top_k,
        "candidate_count": len(candidates),
        "selected_sources": selected_sources,
        "checks": checks,
        "ranked_sources": _ranked_source_records(scored),
        "embedding_top_n_sources": [
            candidate["source_ref"] for _, _, candidate, _ in top_n_scored
        ],
        "reranked_sources": _reranked_source_records(top_n_scored, rerank.ranked_indexes),
        "downstream_tests": dict(downstream["summary"]),
        "downstream_causal_reason": downstream["causal_reason"],
        "provider_traces": sanitized_provider_trace_records(traces),
        "actual_qwen_token_usage": _actual_qwen_token_usage(traces),
        "credentials_recorded": False,
        "report_contains_raw_prompts": False,
        "deterministic_runtime_work": [
            "cosine similarity over provider embeddings",
            "top-N candidate selection",
            "hidden-test execution against a temp repo",
        ],
    }


def write_live_qwen_embedding_baseline_report(
    target: str | Path,
    fixture_root: str | Path,
    api_key: str,
    compatible_base_url: str = DEFAULT_COMPATIBLE_BASE_URL,
    rerank_base_url: str = DEFAULT_RERANK_BASE_URL,
) -> dict[str, Any]:
    report = build_live_qwen_embedding_baseline_report(
        fixture_root=fixture_root,
        api_key=api_key,
        compatible_base_url=compatible_base_url,
        rerank_base_url=rerank_base_url,
    )
    _write_json(target, report)
    return report


def _ranked_source_records(
    scored: list[tuple[float, int, dict[str, Any], ProviderTrace]]
) -> list[dict[str, Any]]:
    return [
        {
            "source_ref": candidate["source_ref"],
            "similarity": round(score, 6),
            "rank_position": position,
        }
        for position, (score, _, candidate, _) in enumerate(scored, start=1)
    ]


def _reranked_source_records(
    top_n_scored: list[tuple[float, int, dict[str, Any], ProviderTrace]],
    ranked_indexes: list[int],
) -> list[dict[str, Any]]:
    return [
        {
            "source_ref": top_n_scored[index][2]["source_ref"],
            "rerank_position": position,
        }
        for position, index in enumerate(ranked_indexes, start=1)
        if index < len(top_n_scored)
    ]


def _actual_qwen_token_usage(traces: list[ProviderTrace]) -> dict[str, int]:
    totals = {"embedding_total_tokens": 0, "rerank_total_tokens": 0}
    for trace in traces:
        total_tokens = int(trace.usage.get("total_tokens", 0) or 0)
        if trace.provider_role == "embedding":
            totals["embedding_total_tokens"] += total_tokens
        elif trace.provider_role == "rerank":
            totals["rerank_total_tokens"] += total_tokens
    return totals


class _PreflightResponse:
    def __init__(self, body: dict[str, Any]) -> None:
        self._body = json.dumps(body).encode("utf-8")
        self.headers: dict[str, str] = {}

    def read(self) -> bytes:
        return self._body

    def __enter__(self) -> _PreflightResponse:
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> bool:
        return False


class _PreflightOpener:
    def __init__(self, responses: list[_PreflightResponse]) -> None:
        self._responses = list(responses)
        self.requests: list[Any] = []

    def __call__(self, request: Any, timeout: int) -> _PreflightResponse:
        self.requests.append(request)
        if not self._responses:
            raise AssertionError("preflight response queue exhausted")
        return self._responses.pop(0)


def _preflight_success_responses() -> list[_PreflightResponse]:
    responses = [_preflight_embedding_response("query-emb", [1.0, 0.0, 0.0], 5)]
    document_vectors = {
        "turn-001": [1.0, 0.0, 0.0],
        "turn-003": [0.95, 0.05, 0.0],
        "turn-005": [0.25, 0.9, 0.0],
    }
    for event_id in [
        "turn-001",
        "turn-002",
        "turn-003",
        "turn-004",
        "turn-005",
        "turn-006",
        "turn-007",
        "turn-008",
        "turn-009",
        "turn-010",
        "turn-011",
        "turn-012",
    ]:
        vector = document_vectors.get(event_id, [0.0, 0.0, 1.0])
        responses.append(_preflight_embedding_response(f"{event_id}-emb", vector, 5))
    responses.append(_preflight_rerank_response([0, 1, 2, 3], 9))
    return responses


def _preflight_embedding_response(
    request_id: str,
    vector: list[float],
    total_tokens: int,
) -> _PreflightResponse:
    return _PreflightResponse(
        {
            "id": request_id,
            "model": TEXT_EMBEDDING_MODEL,
            "data": [{"embedding": vector}],
            "usage": {"total_tokens": total_tokens},
        }
    )


def _preflight_rerank_response(
    indexes: list[int],
    total_tokens: int,
) -> _PreflightResponse:
    return _PreflightResponse(
        {
            "id": "rerank-req",
            "model": RERANK_MODEL,
            "results": [
                {"index": index, "relevance_score": 1.0 - position * 0.1}
                for position, index in enumerate(indexes)
            ],
            "usage": {"total_tokens": total_tokens},
        }
    )


def _request_role_counts(requests: list[Any]) -> dict[str, int]:
    counts: dict[str, int] = {"embedding": 0, "rerank": 0}
    for request in requests:
        url = str(getattr(request, "full_url", ""))
        if url.endswith("/embeddings"):
            counts["embedding"] += 1
        elif url.endswith("/reranks"):
            counts["rerank"] += 1
    return counts


def _embedding_request_contract(requests: list[Any]) -> dict[str, Any]:
    embedding_payloads = [
        _request_payload(request)
        for request in requests
        if str(getattr(request, "full_url", "")).endswith("/embeddings")
    ]
    inputs = [payload.get("input") for payload in embedding_payloads]
    return {
        "request_count": len(embedding_payloads),
        "all_text_embedding_v4": all(
            payload.get("model") == TEXT_EMBEDDING_MODEL
            for payload in embedding_payloads
        ),
        "all_single_text_input": all(isinstance(input_text, str) for input_text in inputs),
        "query_request_count": 1 if embedding_payloads else 0,
        "document_request_count": max(0, len(embedding_payloads) - 1),
    }


def _rerank_request_contract(requests: list[Any]) -> dict[str, Any]:
    rerank_payloads = [
        _request_payload(request)
        for request in requests
        if str(getattr(request, "full_url", "")).endswith("/reranks")
    ]
    return {
        "request_count": len(rerank_payloads),
        "all_qwen3_rerank": all(
            payload.get("model") == RERANK_MODEL for payload in rerank_payloads
        ),
        "all_top_n_matches_document_count": all(
            int(payload.get("top_n", -1)) == len(payload.get("documents", []))
            for payload in rerank_payloads
        ),
        "all_instruct_present": all(
            isinstance(payload.get("instruct"), str) and bool(payload.get("instruct"))
            for payload in rerank_payloads
        ),
    }


def _request_payload(request: Any) -> dict[str, Any]:
    raw = getattr(request, "data", b"{}")
    if isinstance(raw, bytes):
        return json.loads(raw.decode("utf-8"))
    return json.loads(str(raw))


def _downstream_ratio(summary: dict[str, int]) -> str:
    total = int(summary.get("passed", 0)) + int(summary.get("failed", 0))
    return f"{summary.get('passed', 0)}/{total}"


def _write_json(target: str | Path, payload: dict[str, Any]) -> None:
    target_path = Path(target)
    target_path.parent.mkdir(parents=True, exist_ok=True)
    target_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
