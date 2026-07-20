from __future__ import annotations

import json
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from recallpack.budget import count_canonical_json_tokens
from recallpack.compile import CompileRequest, CompileService
from recallpack.downstream import QwenPatchGenerationProvider, run_downstream_proof
from recallpack.evaluation import (
    _cosine_similarity,
    _raw_event_context,
    _raw_event_document,
    load_hero_fixture,
)
from recallpack.live_qwen_contract import (
    DEFAULT_COMPATIBLE_BASE_URL,
    DEFAULT_RERANK_BASE_URL,
    DEFAULT_TEXT_MODEL,
)
from recallpack.locking import ProjectTurnstileRegistry
from recallpack.providers import (
    QwenCloudHTTPClient,
    QwenEmbeddingProvider,
    QwenMemoryDecisionProvider,
    QwenRerankProvider,
    ProviderMemoryDecider,
    ProviderRanker,
    ProviderTrace,
    sanitized_provider_trace_records,
)
from recallpack.storage import SqliteEventStore
from recallpack.observe import ObserveRuntime


def build_live_qwen_e2e_preflight_report(
    fixture_root: str | Path,
    compatible_base_url: str = DEFAULT_COMPATIBLE_BASE_URL,
    rerank_base_url: str = DEFAULT_RERANK_BASE_URL,
    text_model: str = DEFAULT_TEXT_MODEL,
) -> dict[str, Any]:
    fixture = load_hero_fixture(fixture_root)
    opener = _PreflightOpener(_preflight_success_responses(fixture, text_model))
    e2e_report = build_live_qwen_e2e_report(
        fixture_root=fixture_root,
        api_key="placeholder",
        compatible_base_url=compatible_base_url,
        rerank_base_url=rerank_base_url,
        text_model=text_model,
        opener=opener,
    )
    request_role_counts = _request_role_counts(opener.requests)
    memory_contract = _memory_decision_request_contract(opener.requests)
    patch_generation_contract = _patch_generation_request_contract(
        opener.requests,
        expected_allowed_paths=fixture.gold.get("allowed_edit_paths", ["src/retry.py"]),
    )
    expected_embedding_count = (
        2
        + len(fixture.events)
        + _preflight_observe_embedding_count(_preflight_operations(fixture))
    )
    checks = {
        "expected_live_e2e_would_pass_with_contract_responses": (
            e2e_report.get("live_status") == "live_e2e_passed"
        ),
        "required_sources_selected": bool(
            e2e_report.get("checks", {}).get("required_sources_selected")
        ),
        "stale_sources_excluded": bool(
            e2e_report.get("checks", {}).get("stale_sources_excluded")
        ),
        "memory_decision_request_contract_ready": all(
            [
                memory_contract["all_enable_thinking_false"],
                memory_contract["all_tool_choice_function"],
                memory_contract["all_structured_event_metadata"],
                memory_contract["all_decision_policy_present"],
                memory_contract["all_descriptive_tool_schema"],
            ]
        ),
        "embedding_and_rerank_paths_reachable": (
            request_role_counts.get("embedding") == expected_embedding_count
            and request_role_counts.get("rerank") == 2
        ),
        "patch_generation_path_reachable": (
            request_role_counts.get("patch_generation") == 2
            and patch_generation_contract["same_provider_contract"]
        ),
    }
    return {
        "preflight_status": (
            "ready_for_live_e2e_rerun" if all(checks.values()) else "not_ready_for_live_e2e_rerun"
        ),
        "live_qwen_run": False,
        "network_calls_made": False,
        "scenario": f"{_scenario_base(fixture)}_preflight",
        "project_id": e2e_report.get("project_id"),
        "compatible_base_url": compatible_base_url.rstrip("/"),
        "rerank_base_url": rerank_base_url.rstrip("/"),
        "model_name": text_model,
        "request_role_counts": request_role_counts,
        "memory_decision_request_contract": memory_contract,
        "patch_generation_preflight": patch_generation_contract,
        "expected_selected_sources": list(e2e_report.get("selected_sources", [])),
        "expected_downstream_tests": {
            "baseline": _downstream_ratio(
                e2e_report["downstream_patch_generation"]["baseline"]["summary"]
            ),
            "recallpack": _downstream_ratio(
                e2e_report["downstream_patch_generation"]["recallpack"]["summary"]
            ),
        },
        "checks": checks,
        "expected_baseline_selection": dict(e2e_report.get("baseline_selection", {})),
        "provider_trace_roles": [
            trace["provider_role"] for trace in e2e_report.get("provider_traces", [])
        ],
        "actual_qwen_token_usage": e2e_report.get("actual_qwen_token_usage", {}),
        "next_gated_action": (
            "Rerun live Qwen E2E only after explicit approval; preflight does not "
            "read credentials or call Qwen."
        ),
    }


def write_live_qwen_e2e_preflight_report(
    target: str | Path,
    fixture_root: str | Path,
    compatible_base_url: str = DEFAULT_COMPATIBLE_BASE_URL,
    rerank_base_url: str = DEFAULT_RERANK_BASE_URL,
    text_model: str = DEFAULT_TEXT_MODEL,
) -> dict[str, Any]:
    report = build_live_qwen_e2e_preflight_report(
        fixture_root=fixture_root,
        compatible_base_url=compatible_base_url,
        rerank_base_url=rerank_base_url,
        text_model=text_model,
    )
    target_path = Path(target)
    target_path.parent.mkdir(parents=True, exist_ok=True)
    target_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    )
    return report


def build_live_qwen_e2e_report(
    fixture_root: str | Path,
    api_key: str,
    compatible_base_url: str = DEFAULT_COMPATIBLE_BASE_URL,
    rerank_base_url: str = DEFAULT_RERANK_BASE_URL,
    text_model: str = DEFAULT_TEXT_MODEL,
    opener: Any | None = None,
) -> dict[str, Any]:
    fixture = load_hero_fixture(fixture_root)
    fixture_component = _fixture_component(fixture)
    components = _fixture_components(fixture)
    client = QwenCloudHTTPClient(api_key=api_key, opener=opener)
    memory_decider = ProviderMemoryDecider(
        QwenMemoryDecisionProvider(
            client=client,
            compatible_base_url=compatible_base_url,
            model_id=text_model,
        )
    )
    embedding_provider = _TracingEmbeddingProvider(
        QwenEmbeddingProvider(
            client=client,
            compatible_base_url=compatible_base_url,
        )
    )
    ranker = ProviderRanker(
        QwenRerankProvider(
            client=client,
            rerank_base_url=rerank_base_url,
        )
    )
    raw_history_reranker = QwenRerankProvider(
        client=client,
        rerank_base_url=rerank_base_url,
    )
    patch_provider = QwenPatchGenerationProvider(
        client=client,
        compatible_base_url=compatible_base_url,
        model_id=text_model,
    )

    with tempfile.TemporaryDirectory() as tmpdir:
        store = SqliteEventStore(Path(tmpdir) / "live-qwen-e2e.sqlite3")
        runtime = ObserveRuntime(
            store=store,
            decider=memory_decider,
            components=components,
            embedding_provider=embedding_provider,
            turnstile_registry=ProjectTurnstileRegistry(),
        )
        observe_status_codes: list[int] = []
        for event in fixture.events:
            response = runtime.observe(event, now=100 + event.sequence_no)
            observe_status_codes.append(response.status_code)

        compile_result = CompileService(
            store=store,
            ranker=ranker,
            embedding_provider=embedding_provider,
            retrieval_top_n=8,
            components=components,
        ).compile(
            CompileRequest(
                project_id=fixture.gold.get("project_id", "project-a"),
                goal=fixture.gold["goal"],
                component=fixture_component,
                budget_tokens=512,
            )
        )
        baseline_context, baseline_selection, baseline_rerank_trace = (
            _live_raw_history_baseline_context(
                fixture=fixture,
                embedding_provider=embedding_provider,
                rerank_provider=raw_history_reranker,
            )
        )
        baseline_downstream = run_downstream_proof(
            fixture,
            baseline_context,
            "live_embedding_top_n_rerank_baseline",
            patch_provider=patch_provider,
        )
        recallpack_downstream = run_downstream_proof(
            fixture,
            list(compile_result.pack.memories),
            "live_recallpack",
            patch_provider=patch_provider,
        )

    selected_sources = [
        memory["source_ref"] for memory in compile_result.pack.memories
    ]
    required_sources = _required_sources(fixture)
    stale_sources = _stale_sources(fixture)
    provider_traces = [
        *memory_decider.traces,
        *embedding_provider.traces,
        *ranker.traces,
        baseline_rerank_trace,
        *patch_provider.traces,
    ]
    checks = {
        "all_observe_events_completed": all(code == 200 for code in observe_status_codes),
        "required_sources_selected": all(
            source in selected_sources for source in required_sources
        ),
        "stale_sources_excluded": all(
            source not in selected_sources for source in stale_sources
        ),
        "active_retry_selected": "session-a:turn-005" in selected_sources,
        "project_preference_selected": "session-a:turn-003" in selected_sources,
        "stale_retry_excluded": "session-a:turn-001" not in selected_sources,
        "compile_status_ok": compile_result.status_code == 200,
        "baseline_downstream_fails": baseline_downstream["summary"] == {"passed": 1, "failed": 2},
        "baseline_downstream_reported": (
            baseline_downstream["summary"]["passed"]
            + baseline_downstream["summary"]["failed"]
            > 0
        ),
        "recallpack_downstream_passes": recallpack_downstream["summary"] == {"passed": 3, "failed": 0},
    }
    live_status_required_checks = [
        "all_observe_events_completed",
        "required_sources_selected",
        "stale_sources_excluded",
        "compile_status_ok",
        "baseline_downstream_reported",
        "recallpack_downstream_passes",
    ]
    live_status = (
        "live_e2e_passed"
        if all(checks[key] for key in live_status_required_checks)
        else "live_e2e_failed"
    )
    return {
        "live_qwen_run": True,
        "live_status": live_status,
        "run_completed_at": _utc_timestamp(),
        "scenario": _scenario_base(fixture),
        "project_id": fixture.gold.get("project_id", "project-a"),
        "region_base_url": compatible_base_url.rstrip("/"),
        "rerank_base_url": rerank_base_url.rstrip("/"),
        "observed_event_count": len(observe_status_codes),
        "observe_status_counts": _status_counts(observe_status_codes),
        "selected_sources": selected_sources,
        "excluded_sources_checked": stale_sources,
        "checks": checks,
        "live_status_required_checks": live_status_required_checks,
        "baseline_selection": baseline_selection,
        "pack_memory_segment_tokens": count_canonical_json_tokens(
            compile_result.pack.to_canonical_json()
        ),
        "compile_trace": _public_compile_trace(compile_result.trace),
        "downstream_patch_generation": _downstream_patch_generation_payload(
            baseline_downstream,
            recallpack_downstream,
        ),
        "provider_traces": sanitized_provider_trace_records(provider_traces),
        "actual_qwen_token_usage": _actual_qwen_token_usage(provider_traces),
        "qwen_model_work": [
            "memory extraction, type classification, and supersession judgment",
            "candidate memory retrieval with text-embedding-v4",
            "precision reranking with qwen3-rerank",
        ],
        "deterministic_runtime_work": [
            "event ordering and lease fencing",
            "SQLite lifecycle writes and supersession edges",
            "active/superseded lifecycle filtering",
            "cosine similarity over provider embeddings",
            "512-token budget selection",
        ],
    }


def write_live_qwen_e2e_report(
    target: str | Path,
    fixture_root: str | Path,
    api_key: str,
    compatible_base_url: str = DEFAULT_COMPATIBLE_BASE_URL,
    rerank_base_url: str = DEFAULT_RERANK_BASE_URL,
    text_model: str = DEFAULT_TEXT_MODEL,
    opener: Any | None = None,
) -> dict[str, Any]:
    report = build_live_qwen_e2e_report(
        fixture_root=fixture_root,
        api_key=api_key,
        compatible_base_url=compatible_base_url,
        rerank_base_url=rerank_base_url,
        text_model=text_model,
        opener=opener,
    )
    target_path = Path(target)
    target_path.parent.mkdir(parents=True, exist_ok=True)
    target_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    )
    return report


class _TracingEmbeddingProvider:
    def __init__(self, provider: QwenEmbeddingProvider) -> None:
        self._provider = provider
        self.traces: list[ProviderTrace] = []

    def embed_query(self, text: str) -> Any:
        result = self._provider.embed_query(text)
        self.traces.append(result.trace)
        return result

    def embed_document(self, text: str) -> Any:
        result = self._provider.embed_document(text)
        self.traces.append(result.trace)
        return result


def _status_counts(status_codes: list[int]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for status_code in status_codes:
        key = str(status_code)
        counts[key] = counts.get(key, 0) + 1
    return counts


def _public_compile_trace(trace: dict[str, Any]) -> dict[str, Any]:
    return {
        "candidate_count": trace.get("candidate_count"),
        "retrieval_mode": trace.get("retrieval_mode"),
        "embedding_top_n_count": trace.get("embedding_top_n_count"),
        "retrieved_memory_ids": list(trace.get("retrieved_memory_ids", [])),
        "selected_count": trace.get("selected_count"),
        "omitted_memory_ids": list(trace.get("omitted_memory_ids", [])),
    }


def _live_raw_history_baseline_context(
    *,
    fixture: Any,
    embedding_provider: _TracingEmbeddingProvider,
    rerank_provider: QwenRerankProvider,
    retrieval_top_n: int = 4,
    selection_top_k: int = 2,
) -> tuple[list[dict[str, Any]], dict[str, Any], ProviderTrace]:
    candidates = [_raw_event_context(event) for event in fixture.events]
    query = embedding_provider.embed_query(fixture.gold["goal"])
    scored: list[tuple[float, int, dict[str, Any]]] = []
    for index, candidate in enumerate(candidates):
        embedded = embedding_provider.embed_document(_raw_event_document(candidate))
        score = _cosine_similarity(query.embedding, embedded.embedding)
        scored.append((score, index, candidate))

    scored.sort(key=lambda item: (-item[0], item[1]))
    top_n_scored = scored[:retrieval_top_n]
    rerank = rerank_provider.rerank(
        goal=fixture.gold["goal"],
        documents=[_raw_event_document(candidate) for _, _, candidate in top_n_scored],
        instruct="rank raw session events for a coding-agent handoff",
    )
    selected = [
        top_n_scored[index][2]
        for index in rerank.ranked_indexes[:selection_top_k]
        if index < len(top_n_scored)
    ]
    selection = {
        "context_source": "live_embedding_top_n_rerank_raw_history",
        "retrieval_top_n": retrieval_top_n,
        "selection_top_k": selection_top_k,
        "candidate_count": len(candidates),
        "embedding_top_n_sources": [
            candidate["source_ref"] for _, _, candidate in top_n_scored
        ],
        "selected_sources": [candidate["source_ref"] for candidate in selected],
        "ranked_sources": [
            {
                "source_ref": candidate["source_ref"],
                "similarity": round(score, 6),
                "rank_position": position,
            }
            for position, (score, _, candidate) in enumerate(scored, start=1)
        ],
        "reranked_sources": [
            {
                "source_ref": top_n_scored[index][2]["source_ref"],
                "rerank_position": position,
            }
            for position, index in enumerate(rerank.ranked_indexes, start=1)
            if index < len(top_n_scored)
        ],
    }
    return selected, selection, rerank.trace


def _downstream_patch_generation_payload(
    baseline_downstream: dict[str, Any],
    recallpack_downstream: dict[str, Any],
) -> dict[str, Any]:
    baseline_trace = baseline_downstream["patch_generation"]
    recallpack_trace = recallpack_downstream["patch_generation"]
    return {
        "baseline": _downstream_patch_generation_variant(baseline_downstream),
        "recallpack": _downstream_patch_generation_variant(recallpack_downstream),
        "same_provider_contract": (
            baseline_trace["provider_role"] == recallpack_trace["provider_role"]
            and baseline_trace["model_name"] == recallpack_trace["model_name"]
            and baseline_trace["request_purpose"] == recallpack_trace["request_purpose"]
        ),
        "used_gold_patch_variants": (
            baseline_trace["used_gold_patch_variants"]
            or recallpack_trace["used_gold_patch_variants"]
        ),
    }


def _downstream_patch_generation_variant(downstream: dict[str, Any]) -> dict[str, Any]:
    trace = downstream["patch_generation"]
    return {
        "summary": dict(downstream["summary"]),
        "provider_role": trace["provider_role"],
        "model_name": trace["model_name"],
        "request_purpose": trace["request_purpose"],
        "execution_mode": downstream["execution_mode"],
        "accepted": downstream["accepted"],
        "error": downstream.get("error"),
        "output_paths": list(trace.get("output_paths", [])),
        "source_file_paths": list(trace.get("source_file_paths", [])),
        "selected_context_source_refs": list(
            trace.get("selected_context_source_refs", [])
        ),
    }


def _downstream_ratio(summary: dict[str, int]) -> str:
    total = summary["passed"] + summary["failed"]
    return f"{summary['passed']}/{total}"


def _actual_qwen_token_usage(traces: list[ProviderTrace]) -> dict[str, int]:
    totals = {
        "memory_decision_total_tokens": 0,
        "embedding_total_tokens": 0,
        "rerank_total_tokens": 0,
        "patch_generation_total_tokens": 0,
    }
    for trace in traces:
        total_tokens = int(trace.usage.get("total_tokens", 0) or 0)
        if trace.provider_role == "memory_decision":
            totals["memory_decision_total_tokens"] += total_tokens
        elif trace.provider_role == "embedding":
            totals["embedding_total_tokens"] += total_tokens
        elif trace.provider_role == "rerank":
            totals["rerank_total_tokens"] += total_tokens
        elif trace.provider_role == "patch_generation":
            totals["patch_generation_total_tokens"] += total_tokens
    return totals


def _utc_timestamp() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _fixture_component(fixture: Any) -> str:
    return str(fixture.gold.get("component", "retry"))


def _fixture_components(fixture: Any) -> set[str]:
    return {"retry", "auth", "cache", "config", _fixture_component(fixture)}


def _required_sources(fixture: Any) -> list[str]:
    return [str(source) for source in fixture.gold.get("required_sources", [])]


def _stale_sources(fixture: Any) -> list[str]:
    return [str(source) for source in fixture.gold.get("stale_sources", [])]


def _scenario_base(fixture: Any) -> str:
    structure = str(fixture.gold.get("fixture_structure", ""))
    if "projectodyssey" in structure or "projectodyssey" in str(fixture.root).lower():
        return "projectodyssey_observe_compile"
    return "hero_observe_compile"


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


def _preflight_success_responses(fixture: Any, text_model: str) -> list[_PreflightResponse]:
    if isinstance(fixture.gold.get("memory_events"), dict):
        return _fixture_preflight_success_responses(fixture, text_model)
    return _project_a_preflight_success_responses(text_model)


def _project_a_preflight_success_responses(text_model: str) -> list[_PreflightResponse]:
    operations = _project_a_preflight_operations()
    responses = _preflight_observe_responses(
        events=list(range(len(operations))),
        operations=operations,
        text_model=text_model,
    )
    responses.extend(
        [
            _preflight_embedding_response("query-emb", [1.0, 0.0], 5),
            _preflight_rerank_response([0, 1], 7),
            _preflight_embedding_response("raw-query-emb", [1.0, 0.0, 0.0], 5),
            *_preflight_raw_history_embedding_responses(),
            _preflight_rerank_response([0, 1, 2, 3], 9),
            _preflight_patch_generation_response(
                "baseline-patch",
                [
                    {
                        "path": "src/retry.py",
                        "content": (
                            "import time\n\n\n"
                            "def retry(operation, max_attempts=3, delay_seconds=0.1):\n"
                            "    last_error = None\n"
                            "    for attempt in range(max_attempts):\n"
                            "        try:\n"
                            "            return operation()\n"
                            "        except Exception as exc:\n"
                            "            last_error = exc\n"
                            "            if attempt < max_attempts - 1:\n"
                            "                time.sleep(delay_seconds)\n"
                            "    raise last_error\n"
                        ),
                    }
                ],
                text_model,
                20,
            ),
            _preflight_patch_generation_response(
                "recallpack-patch",
                [
                    {
                        "path": "src/retry.py",
                        "content": (
                            "import time\n\n\n"
                            "def retry(operation, max_attempts=5, delay_seconds=0.1):\n"
                            "    last_error = None\n"
                            "    for attempt in range(max_attempts):\n"
                            "        try:\n"
                            "            return operation()\n"
                            "        except Exception as exc:\n"
                            "            last_error = exc\n"
                            "            if attempt < max_attempts - 1:\n"
                            "                time.sleep(delay_seconds * (2 ** attempt))\n"
                            "    raise last_error\n"
                        ),
                    }
                ],
                text_model,
                20,
            ),
        ]
    )
    return responses


def _project_a_preflight_operations() -> list[dict[str, Any]]:
    return [
        _preflight_write_decision("retry_policy", "Use three attempts with a fixed 100 ms delay.", "retry"),
        _preflight_no_op("non_memory_event"),
        _preflight_write_preference("dependency_policy", "Do not add new dependencies."),
        _preflight_no_op("non_memory_event"),
        _preflight_write_decision(
            "retry_policy",
            "Use five attempts with exponential backoff.",
            "retry",
            supersedes=[1],
        ),
        _preflight_no_op("non_memory_event"),
        _preflight_no_op("already_superseded"),
        _preflight_duplicate(1, "same_dependency_preference"),
        _preflight_no_op("non_memory_event"),
        _preflight_write_decision("auth_policy", "Use bearer token validation in auth.", "auth"),
        _preflight_no_op("non_memory_event"),
        _preflight_no_op("handoff_goal"),
    ]


def _fixture_preflight_success_responses(
    fixture: Any,
    text_model: str,
) -> list[_PreflightResponse]:
    planned = _plan_preflight_memory_operations(fixture)
    responses = _preflight_observe_responses(
        events=fixture.events,
        operations=planned["operations"],
        text_model=text_model,
    )
    active_sources = list(planned["active_sources"])
    stale_patch_files, active_patch_files = _preflight_patch_file_variants(fixture)
    responses.extend(
        [
            _preflight_embedding_response("query-emb", [1.0, 0.0], 5),
            _preflight_rerank_response(list(range(len(active_sources))), 7),
            _preflight_embedding_response("raw-query-emb", [1.0, 0.0, 0.0], 5),
            *_preflight_fixture_raw_history_embedding_responses(fixture),
            _preflight_rerank_response([0, 1, 2, 3], 9),
            _preflight_patch_generation_response(
                "baseline-patch",
                stale_patch_files,
                text_model,
                20,
            ),
            _preflight_patch_generation_response(
                "recallpack-patch",
                active_patch_files,
                text_model,
                20,
            ),
        ]
    )
    return responses


def _plan_preflight_memory_operations(fixture: Any) -> dict[str, Any]:
    memory_events = fixture.gold.get("memory_events")
    if not isinstance(memory_events, dict):
        return {"operations": [], "active_sources": []}

    active_candidates: list[dict[str, Any]] = []
    operations: list[dict[str, Any]] = []
    for project_event_seq, event in enumerate(fixture.events, start=1):
        active_order = _preflight_active_candidate_order(active_candidates)
        source_ref = f"{event.session_id}:{event.event_id}"
        operation_spec = memory_events.get(source_ref)
        if operation_spec is None:
            operation_spec = memory_events.get(event.event_id)
        if operation_spec is None:
            operation = _preflight_no_op("non_memory_event")
        else:
            operation = _preflight_operation_from_gold(operation_spec, active_order)
        operations.append(operation)
        active_candidates = _apply_preflight_operation_to_candidates(
            active_candidates=active_candidates,
            active_order=active_order,
            operation=operation,
            source_ref=source_ref,
            project_event_seq=project_event_seq,
        )
    final_active_order = _preflight_active_candidate_order(active_candidates)
    return {
        "operations": operations,
        "active_sources": [candidate["source_ref"] for candidate in final_active_order],
    }


def _preflight_operations(fixture: Any) -> list[dict[str, Any]]:
    if isinstance(fixture.gold.get("memory_events"), dict):
        return list(_plan_preflight_memory_operations(fixture)["operations"])
    return _project_a_preflight_operations()


def _preflight_observe_embedding_count(
    operations: list[dict[str, Any]],
) -> int:
    active_count = 0
    count = 0
    for operation in operations:
        if active_count:
            count += 1
        if operation.get("operation") == "write":
            count += 1
            active_count += 1 - len(operation.get("supersedes_candidate_indexes", []))
    return count


def _preflight_observe_responses(
    *,
    events: list[Any],
    operations: list[dict[str, Any]],
    text_model: str,
) -> list[_PreflightResponse]:
    responses: list[_PreflightResponse] = []
    active_count = 0
    for index, (_event, operation) in enumerate(
        zip(events, operations, strict=True),
        start=1,
    ):
        if active_count:
            responses.append(
                _preflight_embedding_response(
                    f"observe-{index}-query-emb", [1.0, 0.0], 5
                )
            )
        responses.append(_preflight_chat_response(index, operation, text_model))
        if operation.get("operation") == "write":
            responses.append(
                _preflight_embedding_response(
                    f"observe-{index}-document-emb", [1.0, 0.0], 5
                )
            )
            active_count += 1 - len(
                operation.get("supersedes_candidate_indexes", [])
            )
    return responses


def _preflight_active_candidate_order(
    active_candidates: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    ordered = sorted(
        active_candidates,
        key=lambda candidate: (-int(candidate["source_project_event_seq"]), str(candidate["source_ref"])),
    )
    return [
        {
            **candidate,
            "candidate_index": index,
        }
        for index, candidate in enumerate(ordered)
    ]


def _preflight_operation_from_gold(
    operation_spec: dict[str, Any],
    active_order: list[dict[str, Any]],
) -> dict[str, Any]:
    if operation_spec.get("operation") != "write":
        return _preflight_no_op(str(operation_spec.get("reason", "fixture_gold_no_op")))
    memory = operation_spec["memory"]
    supersedes_indexes = [
        _preflight_candidate_index(
            active_order,
            memory_type=str(candidate["type"]),
            subject=str(candidate["subject"]),
            component=candidate.get("component"),
        )
        for candidate in operation_spec.get("supersedes_candidates", [])
    ]
    return {
        "operation": "write",
        "memory": {
            "type": str(memory["type"]),
            "subject": str(memory["subject"]),
            "text": str(memory["text"]),
            "scope_level": str(memory["scope_level"]),
            "component": memory.get("component"),
        },
        "duplicate_of_candidate_index": None,
        "supersedes_candidate_indexes": supersedes_indexes,
        "reason": "fixture_gold_operation",
    }


def _preflight_candidate_index(
    active_order: list[dict[str, Any]],
    memory_type: str,
    subject: str,
    component: str | None,
) -> int:
    for candidate in active_order:
        if (
            candidate["type"] == memory_type
            and candidate["subject"] == subject
            and candidate["component"] == component
        ):
            return int(candidate["candidate_index"])
    raise AssertionError(f"missing preflight candidate for {memory_type}/{subject}/{component}")


def _apply_preflight_operation_to_candidates(
    *,
    active_candidates: list[dict[str, Any]],
    active_order: list[dict[str, Any]],
    operation: dict[str, Any],
    source_ref: str,
    project_event_seq: int,
) -> list[dict[str, Any]]:
    if operation.get("operation") != "write" or not isinstance(operation.get("memory"), dict):
        return list(active_candidates)

    superseded_sources = {
        str(active_order[index]["source_ref"])
        for index in operation.get("supersedes_candidate_indexes", [])
        if 0 <= index < len(active_order)
    }
    next_candidates = [
        candidate
        for candidate in active_candidates
        if str(candidate["source_ref"]) not in superseded_sources
    ]
    memory = operation["memory"]
    next_candidates.append(
        {
            "type": memory["type"],
            "subject": memory["subject"],
            "component": memory["component"],
            "source_ref": source_ref,
            "source_project_event_seq": project_event_seq,
        }
    )
    return next_candidates


def _preflight_chat_response(
    index: int,
    operation: dict[str, Any],
    text_model: str,
) -> _PreflightResponse:
    return _PreflightResponse(
        {
            "id": f"preflight-chat-{index}",
            "model": text_model,
            "choices": [
                {
                    "message": {
                        "tool_calls": [
                            {
                                "type": "function",
                                "function": {
                                    "name": "decide_memory_operation",
                                    "arguments": json.dumps(operation),
                                },
                            }
                        ]
                    }
                }
            ],
            "usage": {"total_tokens": 10},
        }
    )


def _preflight_embedding_response(
    request_id: str,
    vector: list[float],
    total_tokens: int,
) -> _PreflightResponse:
    return _PreflightResponse(
        {
            "id": request_id,
            "model": "text-embedding-v4",
            "data": [{"embedding": _padded_embedding(vector)}],
            "usage": {"total_tokens": total_tokens},
        }
    )


def _padded_embedding(vector: list[float]) -> list[float]:
    if len(vector) > 1024:
        raise ValueError("embedding vector exceeds V4 dimension")
    return [*vector, *([0.0] * (1024 - len(vector)))]


def _preflight_raw_history_embedding_responses() -> list[_PreflightResponse]:
    document_vectors = {
        "turn-001": [1.0, 0.0, 0.0],
        "turn-003": [0.95, 0.05, 0.0],
        "turn-005": [0.25, 0.9, 0.0],
    }
    return [
        _preflight_embedding_response(
            f"raw-{event_id}-emb",
            document_vectors.get(event_id, [0.0, 0.0, 1.0]),
            5,
        )
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
        ]
    ]


def _preflight_fixture_raw_history_embedding_responses(
    fixture: Any,
) -> list[_PreflightResponse]:
    return [
        _preflight_embedding_response(
            f"raw-{event.session_id}-{event.event_id}-emb",
            _preflight_raw_event_vector(f"{event.session_id}:{event.event_id}", fixture),
            5,
        )
        for event in fixture.events
    ]


def _preflight_raw_event_vector(source_ref: str, fixture: Any) -> list[float]:
    if source_ref in _stale_sources(fixture):
        return [1.0, 0.0, 0.0]
    if _is_required_preference_source(source_ref, fixture):
        return [0.95, 0.05, 0.0]
    if source_ref in _required_sources(fixture):
        return [0.25, 0.9, 0.0]
    return [0.0, 0.0, 1.0]


def _preflight_active_memory_vector(source_ref: str, fixture: Any) -> list[float]:
    if source_ref in _required_sources(fixture):
        return [1.0, 0.0]
    return [0.0, 1.0]


def _is_required_preference_source(source_ref: str, fixture: Any) -> bool:
    if source_ref not in _required_sources(fixture):
        return False
    memory_events = fixture.gold.get("memory_events", {})
    if not isinstance(memory_events, dict):
        return False
    event = memory_events.get(source_ref)
    if not isinstance(event, dict):
        return False
    memory = event.get("memory")
    return isinstance(memory, dict) and memory.get("type") == "preference"


def _preflight_rerank_response(indexes: list[int], total_tokens: int) -> _PreflightResponse:
    return _PreflightResponse(
        {
            "id": "rerank-req",
            "model": "qwen3-rerank",
            "results": [
                {"index": index, "relevance_score": 1.0 - position * 0.1}
                for position, index in enumerate(indexes)
            ],
            "usage": {"total_tokens": total_tokens},
        }
    )


def _preflight_patch_file_variants(fixture: Any) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    primary_path = _primary_allowed_edit_path(fixture)
    if primary_path == "src/ci_policy.py":
        return (
            [
                {
                    "path": primary_path,
                    "content": _preflight_stale_ci_policy_source(),
                }
            ],
            [
                {
                    "path": primary_path,
                    "content": _preflight_current_ci_policy_source(),
                }
            ],
        )
    if primary_path == "src/retry.py":
        return (
            [
                {
                    "path": primary_path,
                    "content": (
                        "import time\n\n\n"
                        "def retry(operation, max_attempts=3, delay_seconds=0.1):\n"
                        "    last_error = None\n"
                        "    for attempt in range(max_attempts):\n"
                        "        try:\n"
                        "            return operation()\n"
                        "        except Exception as exc:\n"
                        "            last_error = exc\n"
                        "            if attempt < max_attempts - 1:\n"
                        "                time.sleep(delay_seconds)\n"
                        "    raise last_error\n"
                    ),
                }
            ],
            [
                {
                    "path": primary_path,
                    "content": (
                        "import time\n\n\n"
                        "def retry(operation, max_attempts=5, delay_seconds=0.1):\n"
                        "    last_error = None\n"
                        "    for attempt in range(max_attempts):\n"
                        "        try:\n"
                        "            return operation()\n"
                        "        except Exception as exc:\n"
                        "            last_error = exc\n"
                        "            if attempt < max_attempts - 1:\n"
                        "                time.sleep(delay_seconds * (2 ** attempt))\n"
                        "    raise last_error\n"
                    ),
                }
            ],
        )
    return ([], [])


def _primary_allowed_edit_path(fixture: Any) -> str:
    for path in fixture.gold.get("allowed_edit_paths", []):
        if path != "pyproject.toml":
            return str(path)
    allowed = fixture.gold.get("allowed_edit_paths", [])
    return str(allowed[0]) if allowed else ""


def _preflight_stale_ci_policy_source() -> str:
    return (
        "def handle_jit_crash(error_message):\n"
        "    return {\n"
        "        \"action\": \"retry_workaround\",\n"
        "        \"retry\": True,\n"
        "        \"retry_attempts\": 3,\n"
        "        \"continue_on_error\": True,\n"
        "        \"skip\": True,\n"
        "        \"minimal_reproducer_required\": False,\n"
        "    }\n"
    )


def _preflight_current_ci_policy_source() -> str:
    return (
        "def handle_jit_crash(error_message):\n"
        "    return {\n"
        "        \"action\": \"fail_and_fix_forward\",\n"
        "        \"retry\": False,\n"
        "        \"retry_attempts\": 0,\n"
        "        \"continue_on_error\": False,\n"
        "        \"skip\": False,\n"
        "        \"minimal_reproducer_required\": True,\n"
        "    }\n"
    )


def _preflight_patch_generation_response(
    request_id: str,
    files: list[dict[str, str]],
    text_model: str,
    total_tokens: int,
) -> _PreflightResponse:
    return _PreflightResponse(
        {
            "id": request_id,
            "model": text_model,
            "choices": [
                {
                    "message": {
                        "tool_calls": [
                            {
                                "type": "function",
                                "function": {
                                    "name": "generate_patch",
                                    "arguments": json.dumps({"files": files}),
                                },
                            }
                        ]
                    }
                }
            ],
            "usage": {"total_tokens": total_tokens},
        }
    )


def _preflight_no_op(reason: str) -> dict[str, Any]:
    return {
        "operation": "no_op",
        "memory": None,
        "duplicate_of_candidate_index": None,
        "supersedes_candidate_indexes": [],
        "reason": reason,
    }


def _preflight_duplicate(index: int, reason: str) -> dict[str, Any]:
    return {
        "operation": "duplicate",
        "memory": None,
        "duplicate_of_candidate_index": index,
        "supersedes_candidate_indexes": [],
        "reason": reason,
    }


def _preflight_write_decision(
    subject: str,
    text: str,
    component: str,
    supersedes: list[int] | None = None,
) -> dict[str, Any]:
    return {
        "operation": "write",
        "memory": {
            "type": "decision",
            "subject": subject,
            "text": text,
            "scope_level": "component",
            "component": component,
        },
        "duplicate_of_candidate_index": None,
        "supersedes_candidate_indexes": list(supersedes or []),
        "reason": "preflight_memory_decision",
    }


def _preflight_write_preference(subject: str, text: str) -> dict[str, Any]:
    return {
        "operation": "write",
        "memory": {
            "type": "preference",
            "subject": subject,
            "text": text,
            "scope_level": "project",
            "component": None,
        },
        "duplicate_of_candidate_index": None,
        "supersedes_candidate_indexes": [],
        "reason": "preflight_memory_preference",
    }


def _request_role_counts(requests: list[Any]) -> dict[str, int]:
    counts = {"memory_decision": 0, "embedding": 0, "rerank": 0, "patch_generation": 0}
    for request in requests:
        url = str(getattr(request, "full_url", ""))
        if url.endswith("/chat/completions"):
            tool_name = _chat_request_tool_name(request)
            if tool_name == "generate_patch":
                counts["patch_generation"] += 1
            else:
                counts["memory_decision"] += 1
        elif url.endswith("/embeddings"):
            counts["embedding"] += 1
        elif url.endswith("/reranks"):
            counts["rerank"] += 1
    return counts


def _memory_decision_request_contract(requests: list[Any]) -> dict[str, Any]:
    chat_payloads = [
        json.loads(request.data.decode("utf-8"))
        for request in requests
        if str(getattr(request, "full_url", "")).endswith("/chat/completions")
        and _chat_request_tool_name(request) == "decide_memory_operation"
    ]
    prompt_contracts = [
        json.loads(payload["messages"][1]["content"])
        for payload in chat_payloads
    ]
    schema_properties = [
        payload["tools"][0]["function"]["parameters"]["properties"]
        for payload in chat_payloads
    ]
    source_refs = sorted(
        {
            contract.get("event", {}).get("source_ref", "")
            for contract in prompt_contracts
            if contract.get("event", {}).get("source_ref")
        }
    )
    return {
        "request_count": len(chat_payloads),
        "all_enable_thinking_false": all(
            payload.get("enable_thinking") is False for payload in chat_payloads
        ),
        "all_tool_choice_function": all(
            payload.get("tool_choice", {}).get("type") == "function"
            and payload.get("tool_choice", {}).get("function", {}).get("name")
            == "decide_memory_operation"
            for payload in chat_payloads
        ),
        "all_structured_event_metadata": all(
            _has_structured_event_metadata(contract.get("event", {}))
            for contract in prompt_contracts
        ),
        "all_decision_policy_present": all(
            _has_decision_policy(contract.get("decision_policy", {}))
            for contract in prompt_contracts
        ),
        "all_descriptive_tool_schema": all(
            _has_descriptive_tool_schema(properties)
            for properties in schema_properties
        ),
        "source_refs_seen": source_refs,
    }


def _patch_generation_request_contract(
    requests: list[Any],
    expected_allowed_paths: Any | None = None,
) -> dict[str, Any]:
    expected_paths = {str(path) for path in (expected_allowed_paths or ["src/retry.py"])}
    chat_payloads = [
        json.loads(request.data.decode("utf-8"))
        for request in requests
        if str(getattr(request, "full_url", "")).endswith("/chat/completions")
        and _chat_request_tool_name(request) == "generate_patch"
    ]
    prompt_contracts = [
        json.loads(payload["messages"][1]["content"])
        for payload in chat_payloads
    ]
    return {
        "request_count": len(chat_payloads),
        "same_provider_contract": len(chat_payloads) == 2
        and len({payload.get("model") for payload in chat_payloads}) == 1,
        "all_enable_thinking_false": all(
            payload.get("enable_thinking") is False for payload in chat_payloads
        ),
        "all_tool_choice_function": all(
            payload.get("tool_choice", {}).get("type") == "function"
            and payload.get("tool_choice", {}).get("function", {}).get("name")
            == "generate_patch"
            for payload in chat_payloads
        ),
        "all_allowed_paths_present": all(
            expected_paths.issubset(
                {str(path) for path in contract.get("allowed_edit_paths", [])}
            )
            for contract in prompt_contracts
        ),
        "all_input_fields_present": all(
            {"goal", "selected_context", "allowed_edit_paths"}.issubset(contract)
            for contract in prompt_contracts
        ),
    }


def _chat_request_tool_name(request: Any) -> str:
    payload = json.loads(request.data.decode("utf-8"))
    return str(payload.get("tool_choice", {}).get("function", {}).get("name", ""))


def _has_structured_event_metadata(event: dict[str, Any]) -> bool:
    required = [
        "project_id",
        "session_id",
        "event_id",
        "source_ref",
        "sequence_no",
        "actor",
        "kind",
        "observed_at",
        "text",
    ]
    return all(key in event for key in required)


def _has_decision_policy(policy: dict[str, Any]) -> bool:
    return all(
        key in policy
        for key in [
            "must_write_when",
            "must_supersede_when",
            "must_duplicate_when",
            "must_no_op_when",
        ]
    )


def _has_descriptive_tool_schema(properties: dict[str, Any]) -> bool:
    if not properties.get("operation", {}).get("description"):
        return False
    if not properties.get("memory", {}).get("description"):
        return False
    if not properties.get("supersedes_candidate_indexes", {}).get("description"):
        return False
    memory_variants = properties.get("memory", {}).get("anyOf", [])
    object_variants = [
        variant for variant in memory_variants if variant.get("type") == "object"
    ]
    if not object_variants:
        return False
    memory_properties = object_variants[0].get("properties", {})
    return all(
        bool(memory_properties.get(field, {}).get("description"))
        for field in ["type", "subject", "text", "scope_level", "component"]
    )
