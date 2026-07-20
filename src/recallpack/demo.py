from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from recallpack.evaluation import (
    evaluate_hero_fixture,
    evaluate_micro_suite,
    load_hero_fixture,
)
from recallpack.providers import (
    FakeEmbeddingProvider,
    FakeMemoryDecisionProvider,
    FakeRerankProvider,
    sanitized_provider_trace_records,
)


def discover_secondary_hero_fixture_roots(project_root: str | Path) -> list[Path]:
    """Return complete V3 hero fixtures without treating V4 snapshots as demos."""
    fixtures_root = Path(project_root) / "fixtures"
    discovered: list[Path] = []
    for fixture in sorted(fixtures_root.glob("project-*")):
        if fixture.name == "project-a" or not fixture.is_dir():
            continue
        sessions = fixture / "sessions.jsonl"
        if not sessions.is_file():
            continue
        if not (fixture / "gold.json").is_file() or not (
            fixture / "repo_snapshot"
        ).is_dir():
            raise ValueError(f"incomplete hero fixture: {fixture.name}")
        discovered.append(fixture)
    return discovered


def build_demo_payload(
    project_fixture_root: str | Path,
    micro_suite_root: str | Path,
    live_qwen_trace_path: str | Path | None = None,
    live_qwen_e2e_trace_path: str | Path | None = None,
    fresh_m98_live_rerun_trace_path: str | Path | None = None,
    projectodyssey_live_qwen_e2e_trace_path: str | Path | None = None,
    secondary_fixture_roots: list[str | Path] | None = None,
) -> dict[str, Any]:
    project_fixture_input = Path(project_fixture_root).absolute()
    project_fixture_path = project_fixture_input.resolve()
    project_surface_root = project_fixture_input.parents[1]
    hero_fixture = load_hero_fixture(project_fixture_path)
    hero_result = evaluate_hero_fixture(project_fixture_path)
    micro_report = evaluate_micro_suite(micro_suite_root)
    recallpack_variant = hero_result.variants["recallpack"]
    qwen_payload = _qwen_load_bearing_payload(
        hero_fixture,
        recallpack_variant,
        live_qwen_trace_path=live_qwen_trace_path,
        live_qwen_e2e_trace_path=live_qwen_e2e_trace_path,
        fresh_m98_live_rerun_trace_path=fresh_m98_live_rerun_trace_path,
        projectodyssey_live_qwen_e2e_trace_path=(
            projectodyssey_live_qwen_e2e_trace_path
        ),
        project_surface_root=project_surface_root,
    )
    generalization_fixture_roots = [Path(project_fixture_root)]
    generalization_fixture_roots.extend(
        Path(root) for root in (secondary_fixture_roots or [])
    )
    return {
        "title": "RecallPack",
        "subtitle": "Stale-aware memory lifecycle for coding-agent handoffs",
        "evidence_boundary": _evidence_boundary_payload(),
        "hero_story": _hero_story_payload(hero_result, qwen_payload),
        "handoff_simulator": _handoff_simulator_payload(hero_result, qwen_payload),
        "handoff_replay": _handoff_replay_payload(hero_result),
        "judge_first_screen": _judge_first_screen_payload(hero_result, qwen_payload),
        "views": [
            {"id": "learn", "label": "Learn"},
            {"id": "recall", "label": "Recall"},
            {"id": "evaluate", "label": "Evaluate"},
        ],
        "learn": {
            "goal": hero_fixture.gold["goal"],
            "timeline": [
                {
                    "sequence_no": event.sequence_no,
                    "actor": event.actor,
                    "event_id": event.event_id,
                    "text": event.text,
                }
                for event in hero_fixture.events
            ],
            "memory_lifecycle": _hero_memory_lifecycle(),
        },
        "recall": {
            "goal": hero_fixture.gold["goal"],
            "pipeline": [
                "observe ordered session events",
                "write durable memories",
                "supersede stale decisions",
                "embedding top-N retrieval",
                "rerank active candidates",
                "select a 512-token pack",
            ],
            "variants": [
                _variant_payload("raw_full_history", hero_result.variants["raw_full_history"]),
                _variant_payload(
                    "embedding_top_k_rag",
                    hero_result.variants["embedding_top_k_rag"],
                ),
                _variant_payload("recallpack", recallpack_variant),
            ],
            "pack": {
                "budget_tokens": 512,
                "memory_segment_tokens": recallpack_variant.metrics[
                    "memory_segment_tokens"
                ],
                "memories": recallpack_variant.selected_context,
            },
        },
        "evaluate": {
            "hidden_tests": hero_fixture.gold["hidden_tests"],
            "micro_suite": {
                "case_count": sum(micro_report.raw_counts.values()),
                "evidence_mode": "behavior_contract_fixture_suite",
                "truthfulness_note": (
                    "The micro-suite is a behavior contract fixture suite: "
                    "fixture-authored cases are replayed through the local runtime; "
                    "it is not a broad benchmark."
                ),
                "raw_counts": micro_report.raw_counts,
                "confusion_matrix": micro_report.confusion_matrix,
                "edge_counts": micro_report.edge_counts,
                "metrics": micro_report.metrics,
                "sections": micro_report.sections,
                "positioning": micro_report.positioning,
                "prediction_evidence": micro_report.prediction_evidence,
            },
            "generalization_fixtures": _generalization_fixtures_payload(
                generalization_fixture_roots
            ),
        },
        "qwen_load_bearing": qwen_payload,
        "deployment_proof": {
            "target": "Alibaba Cloud ECS + Docker + SQLite",
            "approval_required": True,
            "runtime_limits": {
                "deployment_replicas": 1,
                "application_workers": 1,
            },
            "public_deployment": {
                "status": "approved_public_ecs_passed",
                "url": "http://101.133.224.223/",
                "platform": "Alibaba Cloud ECS",
                "region": "cn-shanghai",
                "container": "recallpack-cloud",
                "port_mapping": "0.0.0.0:80->8789/tcp",
                "judge_smoke_status": "passed",
                "image": "recallpack-demo:cloud",
                "source_bundle": "latest sanitized bundle",
                "redeployed_at": "2026-07-04",
                "runtime": "ThreadingHTTPServer",
            },
            "non_actions": [
                "no Qwen credentials are required by the deployed demo",
                "no live Qwen calls are made by the Docker runtime",
                "no Docker image was pushed",
                "no hackathon submission is performed by this deployment proof",
            ],
        },
    }


def _evidence_boundary_payload() -> dict[str, Any]:
    return {
        "title": "Evidence Boundary",
        "summary": (
            "Memory lifecycle proof first; Qwen evidence is provider-path "
            "integration evidence, not broad live downstream validation."
        ),
        "sections": [
            {
                "id": "live_qwen",
                "label": "Live Qwen",
                "items": [
                    "provider-path integration evidence: lifecycle filtering held in stored live RecallPack runs",
                    "live raw-history embedding+rerank selected the active retry decision in stored baseline runs",
                    "downstream live delta is one pass and one failed rerun, not a headline metric",
                ],
            },
            {
                "id": "local_demo",
                "label": "Local Demo",
                "items": [
                    "credential-free deterministic replay",
                    "authored local 1/3 vs 3/3 failure-class illustration",
                    "no live Qwen calls are made by the public demo runtime",
                ],
            },
            {
                "id": "behavior_contract",
                "label": "Behavior Contract",
                "items": [
                    "eight curated lifecycle regression fixtures",
                    "tests stale-memory handling behaviors, not a broad benchmark",
                    "raw full history is reference-only and not budget-comparable",
                ],
            },
        ],
        "do_not_claim": [
            "broad coding benchmark improvement",
            "universal retrieval superiority",
            "guaranteed live Qwen downstream success",
            "replacement for agent reasoning",
        ],
        "local_patch_generation_mode": "deterministic_context_keyed_patch_provider",
        "local_baseline_retrieval_mode": "keyword_scored_fake_embedding_rerank",
        "live_qwen_evidence_mode": "stored_sanitized_one_run_trace",
        "micro_suite_mode": "behavior_contract_fixture_suite",
        "structural_claim": (
            "RecallPack stores supersession at write time, when old and new "
            "decisions are both visible, so /compile can structurally exclude "
            "memory the project already reversed."
        ),
        "judge_note": (
            "Local demo uses deterministic fake providers and a deterministic "
            "context-keyed patch provider; local demo makes no live Qwen calls. "
            "Stored live traces support lifecycle filtering, not a measured "
            "live baseline failure rate."
        ),
    }


def _generalization_fixtures_payload(fixture_roots: list[Path]) -> dict[str, Any]:
    fixtures = [_generalization_fixture_payload(root) for root in fixture_roots]
    return {
        "fixture_count": len(fixtures),
        "status": _generalization_status(len(fixtures)),
        "credibility_note": _generalization_credibility_note(len(fixtures)),
        "fixtures": fixtures,
    }


def _generalization_status(fixture_count: int) -> str:
    if fixture_count >= 4:
        return "curated_lifecycle_regression_fixtures"
    if fixture_count >= 2:
        return "two_fixture_lifecycle_proof"
    return "single_fixture_hero_proof"


def _generalization_credibility_note(fixture_count: int) -> str:
    if fixture_count >= 8:
        return (
            "eight local fixtures cover retry, config, cache, serializer, "
            "pagination, realistic API-client auth migration, source-backed AI "
            "provider auth-header mode, and a source-backed ProjectOdyssey JIT "
            "scenario; project-h uses an unrigged keyword provider baseline "
            "with no fixture-authored baseline embedding terms or downrank "
            "phrases. This is stronger local evidence, not a broad benchmark."
        )
    if fixture_count >= 7:
        return (
            "Seven local fixtures cover retry, config, cache, serializer, "
            "pagination, realistic API-client auth migration, and a "
            "source-backed AI provider auth-header mode scenario; project-e "
            "uses non-isomorphic multi-session sparse event ids, project-f uses "
            "a realistic repo-style multi-session flow, and project-g is "
            "inspired by public AI provider/gateway auth-header failure "
            "patterns. This is stronger local evidence, not a broad benchmark."
        )
    if fixture_count >= 6:
        return (
            "M110 covers six local fixtures across retry, config, cache, "
            "serializer, pagination, and a realistic API-client auth migration "
            "scenario; project-e uses non-isomorphic multi-session sparse event "
            "ids and project-f uses a realistic repo-style multi-session flow. "
            "This is stronger local evidence, not a broad benchmark."
        )
    if fixture_count >= 5:
        return (
            "M77 covers five local fixtures across retry, config, cache, "
            "serializer, and pagination stale-memory patterns; project-e uses "
            "non-isomorphic multi-session sparse event ids. This is stronger "
            "local evidence, not a broad benchmark."
        )
    if fixture_count >= 4:
        return (
            "M23 covers four local fixtures across retry, config, cache, and "
            "serializer stale-memory patterns; still local evidence, not a broad "
            "benchmark."
        )
    if fixture_count >= 2:
        return (
            "Second fixture adds a different stale-memory pattern; still a local "
            "fixture suite, not a broad benchmark."
        )
    return (
        "Single hero fixture; add a second independent fixture before claiming "
        "broader generalization."
    )


def _generalization_fixture_payload(fixture_root: Path) -> dict[str, Any]:
    fixture = load_hero_fixture(fixture_root)
    result = evaluate_hero_fixture(fixture_root)
    baseline = result.variants["embedding_top_k_rag"]
    recallpack = result.variants["recallpack"]
    return {
        "project_id": fixture.gold.get("project_id", fixture.events[0].project_id),
        "component": fixture.gold.get("component", "retry"),
        "fixture_structure": fixture.gold.get("fixture_structure", "single_session_linear_turn_ids"),
        "goal": fixture.gold["goal"],
        "baseline_downstream_tests": _downstream_ratio(baseline.downstream),
        "recallpack_downstream_tests": _downstream_ratio(recallpack.downstream),
        "baseline_selected_sources": [
            item["source_ref"] for item in baseline.selected_context
        ],
        "recallpack_selected_sources": [
            item["source_ref"] for item in recallpack.selected_context
        ],
        "baseline_causal_reason": baseline.downstream["causal_reason"],
        "recallpack_causal_reason": recallpack.downstream["causal_reason"],
        "baseline_rejection_code": baseline.downstream.get("error"),
        "recallpack_rejection_code": recallpack.downstream.get("error"),
    }


def _judge_first_screen_payload(
    hero_result: Any,
    qwen_payload: dict[str, Any],
) -> dict[str, Any]:
    raw_full_history = hero_result.variants["raw_full_history"]
    baseline = hero_result.variants["embedding_top_k_rag"]
    recallpack = hero_result.variants["recallpack"]
    return {
        "positioning": "MemoryAgent stale-aware lifecycle proof for coding-agent handoffs",
        "comparison": [
            {
                "id": "raw_full_history",
                "label": "Raw full history",
                "role": "reference_not_budget_comparable",
                "downstream_tests": _downstream_ratio(raw_full_history.downstream),
                "selection_source": raw_full_history.compile_trace["selection_source"],
                "fairness_note": "all 12 events; useful as coverage reference, not a budget baseline",
            },
            {
                "id": "embedding_top_k_rag",
                "label": "Keyword fake-embedding + rerank RAG",
                "role": "computed_budget_baseline",
                "downstream_tests": _downstream_ratio(baseline.downstream),
                "source_recall_score": f"{baseline.metrics['hidden_test_pass_count']}/3",
                "selection_source": baseline.compile_trace["selection_source"],
                "fairness_note": (
                    "computed from raw event text with fake embeddings/rerank; "
                    "not source-picked from gold selected-source IDs, but local "
                    "scoring terms are fixture-authored"
                ),
            },
            {
                "id": "recallpack",
                "label": "RecallPack",
                "role": "stale_aware_memory_lifecycle",
                "downstream_tests": _downstream_ratio(recallpack.downstream),
                "selection_source": "active_memory_compile",
                "fairness_note": "uses active lifecycle state, rerank, and fixed budget selection",
            },
        ],
        "downstream_proof": (
            "Both baseline and RecallPack patches are generated by the same "
            "local deterministic context-keyed patch provider from goal plus "
            "selected context, then run in temp repo fixture tests against "
            "fixture repo_snapshot. The stored live Qwen E2E trace separately "
            "shows one approved model-in-the-loop patch generation run."
        ),
        "qwen_load_bearing": {
            "live_status": qwen_payload["live_status"],
            "standalone_contract_status": qwen_payload["standalone_contract_status"],
            "live_qwen_e2e_status": qwen_payload["live_qwen_e2e_status"],
            "stored_live_qwen_e2e_status": qwen_payload["stored_live_qwen_e2e_status"],
            "fresh_m98_live_rerun_status": qwen_payload[
                "fresh_m98_live_rerun_status"
            ],
            "model_work": list(qwen_payload["qwen_model_work"]),
            "deterministic_runtime_work": list(qwen_payload["deterministic_runtime_work"]),
            "local_mode": (
                "local tests use fake providers or the checked-in sanitized live trace; "
                "no credentials required"
            ),
        },
    }


def _handoff_simulator_payload(
    hero_result: Any,
    qwen_payload: dict[str, Any],
) -> dict[str, Any]:
    baseline = hero_result.variants["embedding_top_k_rag"]
    recallpack = hero_result.variants["recallpack"]
    return {
        "title": "First-Run Handoff Simulator",
        "task": "Update the retry helper to the current project policy.",
        "flow": [
            {
                "id": "incoming_task",
                "label": "Fresh agent receives task",
                "evidence": "new session has no implicit prior context",
            },
            {
                "id": "raw_history_baseline",
                "label": "Baseline recalls raw history",
                "evidence": "keyword-scored fake-embedding + rerank includes superseded retry memory",
            },
            {
                "id": "recallpack_compile",
                "label": "RecallPack compiles active memory",
                "evidence": "superseded memory is filtered before rerank and budget selection",
            },
            {
                "id": "downstream_hidden_tests",
                "label": "Both patches run fixture tests",
                "evidence": "same temp repo, same fixture tests, different handoff context",
            },
        ],
        "baseline": {
            "label": "Baseline stale handoff",
            "context_mode": baseline.compile_trace["selection_source"],
            "selected_sources": [
                item["source_ref"] for item in baseline.selected_context
            ],
            "hidden_tests": _downstream_ratio(baseline.downstream),
            "patch_signal": "max_attempts=3 fixed-delay retry patch",
            "causal_reason": baseline.downstream["causal_reason"],
        },
        "recallpack": {
            "label": "RecallPack active handoff",
            "context_mode": "active_memory_lifecycle_pack",
            "selected_sources": [
                item["source_ref"] for item in recallpack.selected_context
            ],
            "hidden_tests": _downstream_ratio(recallpack.downstream),
            "patch_signal": "max_attempts=5 exponential-backoff retry patch",
            "causal_reason": recallpack.downstream["causal_reason"],
        },
        "why_it_wins": [
            "local replay baseline retrieves stale raw history and writes the old retry policy",
            "RecallPack supersedes stale memory before compile",
            "RecallPack keeps the active retry decision plus dependency preference inside the 512-token pack",
            "both patches are executed in a temp repo against the same fixture tests",
        ],
        "qwen_boundary": {
            "live_status": qwen_payload["live_status"],
            "standalone_contract_status": qwen_payload["standalone_contract_status"],
            "live_observe_compile_e2e_status": qwen_payload["live_qwen_e2e_status"],
            "stored_live_qwen_e2e_status": qwen_payload["stored_live_qwen_e2e_status"],
            "fresh_m98_live_rerun_status": qwen_payload[
                "fresh_m98_live_rerun_status"
            ],
            "first_screen_lines": _qwen_first_screen_lines(qwen_payload),
            "model_work": list(qwen_payload["qwen_model_work"]),
            "runtime_work": list(qwen_payload["deterministic_runtime_work"]),
        },
    }


def _handoff_replay_payload(hero_result: Any) -> dict[str, Any]:
    baseline = hero_result.variants["embedding_top_k_rag"]
    recallpack = hero_result.variants["recallpack"]
    baseline_sources = [item["source_ref"] for item in baseline.selected_context]
    recallpack_sources = [item["source_ref"] for item in recallpack.selected_context]
    return {
        "title": "Deterministic Stale-Memory Failure Replay",
        "status": "local_fixture_evidence",
        "mode_label": "Deterministic scripted replay",
        "task": "Update the retry helper to the current project policy.",
        "default_step_id": "stale_context",
        "play_label": "Replay handoff",
        "evidence_mode": "existing downstream temp-repo patch and fixture-test execution",
        "local_patch_generation_mode": "deterministic_context_keyed_patch_provider",
        "structural_claim": (
            "This is an authored deterministic replay of a stale-handoff "
            "failure class. Stored live Qwen runs support the lifecycle filter: "
            "superseded memory was excluded before active memory was packed."
        ),
        "truthfulness_note": (
            "This local replay uses a deterministic context-keyed patch provider, "
            "not live Qwen inference."
        ),
        "claims_live_qwen_e2e": False,
        "steps": [
            {
                "id": "stale_context",
                "variant_id": "embedding_top_k_rag",
                "label": "Stale context selected",
                "headline": "Baseline retrieves a superseded retry decision",
                "body": (
                    "The raw-history fake-embedding top-N baseline pulls the old "
                    "three-attempt retry instruction into the handoff."
                ),
                "memory_status": "superseded raw session memory selected",
                "selected_sources": baseline_sources,
                "hidden_tests": _downstream_ratio(baseline.downstream),
                "patch_signal": "context contains stale retry policy",
                "result": "stale_context_selected",
                "evidence": "keyword-scored fake-embedding + rerank raw event context",
            },
            {
                "id": "wrong_patch",
                "variant_id": "embedding_top_k_rag",
                "label": "Wrong retry patch",
                "headline": "Fresh agent writes the old retry behavior",
                "body": baseline.downstream["causal_reason"],
                "memory_status": "superseded memory caused stale action",
                "selected_sources": baseline_sources,
                "hidden_tests": _downstream_ratio(baseline.downstream),
                "patch_signal": "max_attempts=3 fixed-delay retry patch",
                "result": "wrong_retry_patch",
                "evidence": "patch applied in temp repo; fixture tests pass 1/3",
            },
            {
                "id": "active_memory_pack",
                "variant_id": "recallpack",
                "label": "Active memory pack",
                "headline": "RecallPack filters stale memory before compile",
                "body": (
                    "The pack keeps the active retry decision and dependency "
                    "preference under the fixed 512-token budget."
                ),
                "memory_status": "active lifecycle memories selected",
                "selected_sources": recallpack_sources,
                "hidden_tests": _downstream_ratio(recallpack.downstream),
                "patch_signal": "active decision plus dependency preference",
                "result": "active_memory_pack_selected",
                "evidence": "embedding top-N -> qwen3-rerank -> budget selector",
            },
            {
                "id": "passing_patch",
                "variant_id": "recallpack",
                "label": "Passing retry patch",
                "headline": "Fresh agent writes current retry behavior",
                "body": recallpack.downstream["causal_reason"],
                "memory_status": "active memory caused current action",
                "selected_sources": recallpack_sources,
                "hidden_tests": _downstream_ratio(recallpack.downstream),
                "patch_signal": "max_attempts=5 exponential-backoff retry patch",
                "result": "correct_retry_patch",
                "evidence": "patch applied in temp repo; fixture tests pass 3/3",
            },
        ],
    }


def _downstream_ratio(downstream: dict[str, Any]) -> str:
    summary = downstream["summary"]
    return f"{summary['passed']}/{summary['passed'] + summary['failed']}"


def _hero_story_payload(hero_result: Any, qwen_payload: dict[str, Any]) -> dict[str, Any]:
    baseline = hero_result.variants["embedding_top_k_rag"]
    recallpack = hero_result.variants["recallpack"]
    return {
        "headline": "RecallPack makes stale-decision exclusion structural",
        "failure_summary": (
            "The local replay shows how budgeted retrieval can carry a "
            "superseded decision into a handoff. RecallPack filters superseded "
            "memory before rerank and budget selection."
        ),
        "baseline": {
            "label": "Embedding top-N + rerank stale baseline",
            "test_summary": _downstream_test_summary(baseline.downstream),
            "patch_signal": "max_attempts=3 fixed-delay retry patch",
            "causal_reason": baseline.downstream["causal_reason"],
        },
        "recallpack": {
            "label": "RecallPack active-memory handoff",
            "test_summary": _downstream_test_summary(recallpack.downstream),
            "patch_signal": "max_attempts=5 exponential-backoff retry patch",
            "causal_reason": recallpack.downstream["causal_reason"],
        },
        "retrieval_path": [
            "embedding top-N",
            "qwen3-rerank",
            "512-token budget selector",
        ],
        "patch_generation": _patch_generation_summary(baseline, recallpack),
        "memory_lifecycle_summary": {
            "superseded": ["mem_retry_old"],
            "active": ["mem_retry_current", "mem_dependency_policy"],
        },
        "live_qwen_status": qwen_payload["live_status"],
        "live_qwen_run": qwen_payload["live_qwen_run"],
    }


def _patch_generation_summary(baseline: Any, recallpack: Any) -> dict[str, Any]:
    baseline_generation = baseline.downstream["patch_generation"]
    recallpack_generation = recallpack.downstream["patch_generation"]
    return {
        "provider_role": baseline_generation["provider_role"],
        "request_purpose": baseline_generation["request_purpose"],
        "local_mode": "deterministic_context_keyed_patch_provider",
        "live_mode": "stored_qwen_e2e_trace_only",
        "truthfulness_note": (
            "Local downstream proof uses a local deterministic context-keyed "
            "patch provider; live Qwen patch generation is evidenced only by "
            "the stored sanitized E2E trace."
        ),
        "same_provider_contract": (
            baseline_generation["provider_role"] == recallpack_generation["provider_role"]
            and baseline_generation["model_name"] == recallpack_generation["model_name"]
            and baseline_generation["request_purpose"]
            == recallpack_generation["request_purpose"]
        ),
        "used_gold_patch_variants": (
            baseline_generation["used_gold_patch_variants"]
            or recallpack_generation["used_gold_patch_variants"]
        ),
        "baseline_model_name": baseline_generation["model_name"],
        "recallpack_model_name": recallpack_generation["model_name"],
        "input_fields": list(baseline_generation["input_fields"]),
    }


def _downstream_test_summary(downstream: dict[str, Any]) -> dict[str, int]:
    passed = int(downstream["summary"]["passed"])
    failed = int(downstream["summary"]["failed"])
    return {
        "passed": passed,
        "failed": failed,
        "total": passed + failed,
    }


def _qwen_load_bearing_payload(
    hero_fixture: Any,
    recallpack_variant: Any,
    live_qwen_trace_path: str | Path | None = None,
    live_qwen_e2e_trace_path: str | Path | None = None,
    fresh_m98_live_rerun_trace_path: str | Path | None = None,
    projectodyssey_live_qwen_e2e_trace_path: str | Path | None = None,
    project_surface_root: Path | None = None,
) -> dict[str, Any]:
    live_payload = _load_live_qwen_trace(live_qwen_trace_path)
    e2e_payload = _load_live_qwen_trace(live_qwen_e2e_trace_path)
    fresh_m98_payload = _load_live_qwen_trace(fresh_m98_live_rerun_trace_path)
    projectodyssey_payload = _load_live_qwen_trace(
        projectodyssey_live_qwen_e2e_trace_path
    )
    e2e_status = _live_qwen_e2e_status_from_payload(e2e_payload)
    fresh_m98_status = _fresh_m98_live_rerun_status_from_payload(fresh_m98_payload)
    fresh_m98_source = _display_trace_path(fresh_m98_live_rerun_trace_path)
    fresh_m98_summary = _fresh_m98_live_rerun_summary(fresh_m98_payload)
    projectodyssey_status = _live_qwen_e2e_status_from_payload(projectodyssey_payload)
    projectodyssey_source = _display_trace_path(projectodyssey_live_qwen_e2e_trace_path)
    projectodyssey_summary = _live_e2e_downstream_summary(projectodyssey_payload)
    if live_payload is not None:
        return _with_live_qwen_e2e_status(
            _normalize_live_qwen_payload(live_payload),
            e2e_status,
            e2e_payload,
            fresh_m98_status,
            fresh_m98_source,
            fresh_m98_summary,
            projectodyssey_status,
            projectodyssey_source,
            projectodyssey_summary,
            live_qwen_e2e_trace_path,
            project_surface_root,
        )

    traces = []
    selected_context = list(recallpack_variant.selected_context)
    memory_provider = FakeMemoryDecisionProvider(
        tool_arguments={
            "operation": "write",
            "memory": {
                "type": "decision",
                "subject": "retry_policy",
                "text": "Use five attempts with exponential backoff.",
                "scope_level": "component",
                "component": "retry",
            },
            "duplicate_of_candidate_index": None,
            "supersedes_candidate_indexes": [0],
            "reason": "updated_retry_policy",
        }
    )
    memory_decision = memory_provider.decide_memory_operation(
        event_text=hero_fixture.events[4].text,
        candidate_payloads=[
            {
                "type": "decision",
                "scope": "component:retry",
                "subject": "retry_policy",
                "source_ref": "session-a:turn-001",
            }
        ],
        tool_schema={"name": "decide_memory_operation"},
    )
    traces.append(memory_decision.trace)

    embedding_provider = FakeEmbeddingProvider()
    traces.append(embedding_provider.embed_query(hero_fixture.gold["goal"]).trace)
    traces.append(embedding_provider.embed_document(selected_context[0]["text"]).trace)

    rerank_provider = FakeRerankProvider(ranked_indexes=list(range(len(selected_context))))
    rerank = rerank_provider.rerank(
        goal=hero_fixture.gold["goal"],
        documents=[memory["text"] for memory in selected_context],
        instruct="rank active memories for a coding-agent handoff",
    )
    traces.append(rerank.trace)

    payload = {
        "live_qwen_run": False,
        "live_status": "gated_not_run",
        "standalone_contract_status": "gated_not_run",
        "live_qwen_e2e_status": e2e_status,
        "stored_live_qwen_e2e_status": e2e_status,
        "fresh_m98_live_rerun_status": fresh_m98_status,
        "fresh_m98_live_rerun_source": fresh_m98_source,
        "fresh_m98_live_rerun_summary": fresh_m98_summary,
        "projectodyssey_live_e2e_status": projectodyssey_status,
        "projectodyssey_live_e2e_source": projectodyssey_source,
        "projectodyssey_live_e2e_summary": projectodyssey_summary,
        "provider_traces": sanitized_provider_trace_records(traces),
        "qwen_model_work": [
            "memory extraction, type classification, and supersession judgment",
            "candidate memory retrieval with text-embedding-v4",
            "precision reranking with qwen3-rerank",
        ],
        "deterministic_runtime_work": [
            "event ordering and lease fencing",
            "schema validation and failure handling",
            "active/superseded lifecycle filtering",
            "512-token budget selection",
            "PACK.md and recallpack.json assembly",
        ],
    }
    payload["trace_explorer"] = _qwen_trace_explorer(
        payload,
        e2e_payload,
        e2e_trace_path=live_qwen_e2e_trace_path,
        project_surface_root=project_surface_root,
    )
    return payload


def _load_live_qwen_trace(path: str | Path | None) -> dict[str, Any] | None:
    if path is None:
        return None
    trace_path = Path(path)
    if not trace_path.is_file():
        return None
    parsed = json.loads(trace_path.read_text())
    return parsed if isinstance(parsed, dict) else None


def _live_qwen_e2e_status(path: str | Path | None) -> str:
    payload = _load_live_qwen_trace(path)
    return _live_qwen_e2e_status_from_payload(payload)


def _live_qwen_e2e_status_from_payload(payload: dict[str, Any] | None) -> str:
    if payload is None:
        return "not_claimed"
    status = payload.get("live_status") or payload.get("live_qwen_e2e_status")
    return str(status) if status else "not_claimed"


def _fresh_m98_live_rerun_status_from_payload(payload: dict[str, Any] | None) -> str:
    if payload is None:
        return "gated_not_run"
    required_m98_fields = (
        "run_completed_at",
        "baseline_selection",
        "live_status_required_checks",
        "downstream_patch_generation",
    )
    if not all(payload.get(field) for field in required_m98_fields):
        return "gated_not_run"
    status = _live_qwen_e2e_status_from_payload(payload)
    if status == "live_e2e_passed":
        return "passed"
    if status == "live_e2e_failed":
        return "live_e2e_failed"
    return status


def _fresh_m98_live_rerun_summary(payload: dict[str, Any] | None) -> str:
    if payload is None:
        return "not run"
    status = _fresh_m98_live_rerun_status_from_payload(payload)
    if status == "gated_not_run":
        return "not run"
    downstream = payload.get("downstream_patch_generation")
    if not isinstance(downstream, dict):
        return status
    baseline = _variant_ratio(downstream.get("baseline"))
    recallpack = _variant_ratio(downstream.get("recallpack"))
    return f"{status}: baseline {baseline}; RecallPack {recallpack}"


def _live_e2e_downstream_summary(payload: dict[str, Any] | None) -> str:
    if payload is None:
        return "not run"
    status = _live_qwen_e2e_status_from_payload(payload)
    downstream = payload.get("downstream_patch_generation")
    if not isinstance(downstream, dict):
        return status
    baseline = _variant_ratio(downstream.get("baseline"))
    recallpack = _variant_ratio(downstream.get("recallpack"))
    return f"{status}: baseline {baseline}; RecallPack {recallpack}"


def _variant_ratio(value: Any) -> str:
    if not isinstance(value, dict):
        return "not recorded"
    summary = value.get("summary")
    if not isinstance(summary, dict):
        return "not recorded"
    passed = int(summary.get("passed", 0) or 0)
    failed = int(summary.get("failed", 0) or 0)
    total = passed + failed
    return f"{passed}/{total}" if total else "0/0"


def _display_trace_path(path: str | Path | None) -> str:
    if path is None:
        return "not_provided"
    text = Path(path).as_posix()
    marker = "docs/submission/"
    index = text.find(marker)
    return text[index:] if index >= 0 else text


def _with_live_qwen_e2e_status(
    payload: dict[str, Any],
    e2e_status: str,
    e2e_payload: dict[str, Any] | None = None,
    fresh_m98_status: str | None = None,
    fresh_m98_source: str | None = None,
    fresh_m98_summary: str | None = None,
    projectodyssey_status: str | None = None,
    projectodyssey_source: str | None = None,
    projectodyssey_summary: str | None = None,
    e2e_trace_path: str | Path | None = None,
    project_surface_root: Path | None = None,
) -> dict[str, Any]:
    updated = dict(payload)
    updated["standalone_contract_status"] = str(updated.get("live_status", "gated_not_run"))
    updated["live_qwen_e2e_status"] = e2e_status
    updated["stored_live_qwen_e2e_status"] = e2e_status
    updated["fresh_m98_live_rerun_status"] = (
        fresh_m98_status
        if fresh_m98_status is not None
        else _fresh_m98_live_rerun_status_from_payload(e2e_payload)
    )
    updated["fresh_m98_live_rerun_source"] = fresh_m98_source or "not_provided"
    updated["fresh_m98_live_rerun_summary"] = fresh_m98_summary or "not run"
    updated["projectodyssey_live_e2e_status"] = (
        projectodyssey_status or "not_claimed"
    )
    updated["projectodyssey_live_e2e_source"] = (
        projectodyssey_source or "not_provided"
    )
    updated["projectodyssey_live_e2e_summary"] = (
        projectodyssey_summary or "not run"
    )
    updated["trace_explorer"] = _qwen_trace_explorer(
        updated,
        e2e_payload,
        e2e_trace_path=e2e_trace_path,
        project_surface_root=project_surface_root,
    )
    return updated


def _qwen_first_screen_lines(qwen_payload: dict[str, Any]) -> list[str]:
    contract = str(qwen_payload.get("standalone_contract_status", "gated_not_run"))
    e2e = str(qwen_payload.get("live_qwen_e2e_status", "not_claimed"))
    fresh_m98 = str(qwen_payload.get("fresh_m98_live_rerun_status", "gated_not_run"))
    projectodyssey = str(
        qwen_payload.get("projectodyssey_live_e2e_status", "not_claimed")
    )
    contract_label = "passed" if contract == "live_contract_passed" else "not run"
    if e2e == "live_e2e_passed" and fresh_m98 == "live_e2e_failed":
        e2e_label = "one pass; fresh rerun failed"
        lifecycle_label = "held in stored live runs"
    elif e2e == "live_e2e_passed":
        e2e_label = "one stored pass"
        lifecycle_label = "held in stored passing run"
    else:
        e2e_label = "not claimed"
        lifecycle_label = "not claimed"
    if projectodyssey == "live_e2e_passed":
        projectodyssey_label = "passed"
    elif projectodyssey == "live_e2e_failed":
        projectodyssey_label = "failed; stored as evidence"
    else:
        projectodyssey_label = "not claimed"
    lines = [
        f"Standalone Qwen API smoke: {contract_label}",
        f"Stored live provider-path E2E: {e2e_label}",
    ]
    if projectodyssey != "not_claimed":
        lines.append(f"ProjectOdyssey live E2E: {projectodyssey_label}")
    lines.append(f"Lifecycle filtering: {lifecycle_label}")
    return lines


def _normalize_live_qwen_payload(payload: dict[str, Any]) -> dict[str, Any]:
    live_status = payload.get("live_status", "live_trace_present")
    return {
        "live_qwen_run": bool(payload.get("live_qwen_run")),
        "live_status": live_status,
        "standalone_contract_status": live_status,
        "live_qwen_e2e_status": "not_claimed",
        "stored_live_qwen_e2e_status": "not_claimed",
        "fresh_m98_live_rerun_status": "gated_not_run",
        "fresh_m98_live_rerun_source": "not_provided",
        "fresh_m98_live_rerun_summary": "not run",
        "projectodyssey_live_e2e_status": "not_claimed",
        "projectodyssey_live_e2e_source": "not_provided",
        "projectodyssey_live_e2e_summary": "not run",
        "provider_traces": list(payload.get("provider_traces", [])),
        "actual_qwen_token_usage": dict(payload.get("actual_qwen_token_usage", {})),
        "contract_summary": list(payload.get("contract_summary", [])),
        "qwen_model_work": list(
            payload.get(
                "qwen_model_work",
                [
                    "memory extraction, type classification, and supersession judgment",
                    "candidate memory retrieval with text-embedding-v4",
                    "precision reranking with qwen3-rerank",
                ],
            )
        ),
        "deterministic_runtime_work": list(
            payload.get(
                "deterministic_runtime_work",
                [
                    "event ordering and lease fencing",
                    "schema validation and failure handling",
                    "active/superseded lifecycle filtering",
                    "512-token budget selection",
                    "PACK.md and recallpack.json assembly",
                ],
            )
        ),
    }


def _qwen_trace_explorer(
    qwen_payload: dict[str, Any],
    e2e_payload: dict[str, Any] | None = None,
    *,
    e2e_trace_path: str | Path | None = None,
    project_surface_root: Path | None = None,
) -> dict[str, Any]:
    source_payload = e2e_payload if e2e_payload is not None else qwen_payload
    traces = list(source_payload.get("provider_traces", qwen_payload.get("provider_traces", [])))
    usage = dict(source_payload.get("actual_qwen_token_usage", {}))
    compile_trace = dict(source_payload.get("compile_trace", {}))
    downstream = dict(source_payload.get("downstream_patch_generation", {}))
    selected_sources = list(source_payload.get("selected_sources", []))
    excluded_sources = list(source_payload.get("excluded_sources_checked", []))
    status = str(
        source_payload.get("live_status")
        or source_payload.get("live_qwen_e2e_status")
        or qwen_payload.get("live_qwen_e2e_status")
        or qwen_payload.get("live_status", "gated_not_run")
    )
    role_summary = _qwen_trace_role_summary(traces, usage)
    source, source_kind, display_title = _trace_explorer_provenance(
        e2e_trace_path,
        has_e2e_payload=e2e_payload is not None,
        project_surface_root=project_surface_root,
    )
    provenance_verified = source_kind != "explicit_trace_override_unverified_provenance"
    return {
        "status": status,
        "source": source,
        "source_kind": source_kind,
        "display_title": display_title,
        "observed_event_count": int(source_payload.get("observed_event_count", 0) or 0),
        "selected_sources": selected_sources,
        "excluded_sources_checked": excluded_sources,
        "role_summary": role_summary,
        "stages": _qwen_trace_stages(role_summary, compile_trace, downstream),
        "downstream_summary": _qwen_downstream_trace_summary(downstream),
        "safety_boundary": {
            "sanitized_trace_only": provenance_verified,
            "provenance_verified": provenance_verified,
            "no_credentials": True,
            "prompts_redacted": True,
            "no_raw_memory_text": True,
            "local_demo_no_live_calls": True,
            "stored_trace_no_live_call": True,
        },
    }


def _trace_explorer_provenance(
    e2e_trace_path: str | Path | None,
    *,
    has_e2e_payload: bool,
    project_surface_root: Path | None,
) -> tuple[str, str, str]:
    if not has_e2e_payload:
        return (
            "local_demo_provider_trace",
            "local_fake_provider_trace",
            "Stored Live Qwen Trace",
        )
    surface_root = (
        project_surface_root or Path(__file__).resolve().parents[2]
    ).absolute()
    checked_in_path = (
        surface_root
        / "docs"
        / "submission"
        / "live-qwen-e2e-trace.json"
    ).absolute()
    candidate_path = (
        Path(e2e_trace_path).absolute() if e2e_trace_path is not None else None
    )
    if (
        candidate_path == checked_in_path
        and candidate_path is not None
        and not _path_has_symlink(candidate_path, surface_root)
    ):
        return (
            "docs/submission/live-qwen-e2e-trace.json",
            "checked_in_sanitized_trace",
            "Stored Live Qwen Trace",
        )
    return (
        "explicit_live_qwen_e2e_trace_override",
        "explicit_trace_override_unverified_provenance",
        "Explicit E2E Trace Override",
    )


def _path_has_symlink(path: Path, root: Path) -> bool:
    current = path
    while current != root:
        if current.is_symlink():
            return True
        if root not in current.parents:
            return True
        current = current.parent
    return root.is_symlink()


def _qwen_trace_role_summary(
    traces: list[dict[str, Any]],
    usage: dict[str, Any],
) -> list[dict[str, Any]]:
    role_order = ["memory_decision", "embedding", "rerank", "patch_generation"]
    token_keys = {
        "memory_decision": "memory_decision_total_tokens",
        "embedding": "embedding_total_tokens",
        "rerank": "rerank_total_tokens",
        "patch_generation": "patch_generation_total_tokens",
    }
    grouped: dict[str, list[dict[str, Any]]] = {}
    for trace in traces:
        role = str(trace.get("provider_role", "unknown"))
        grouped.setdefault(role, []).append(trace)
    summaries = []
    for role in role_order:
        role_traces = grouped.pop(role, [])
        if role_traces:
            summaries.append(_qwen_trace_role_row(role, role_traces, token_keys, usage))
    for role in sorted(grouped):
        summaries.append(_qwen_trace_role_row(role, grouped[role], token_keys, usage))
    return summaries


def _qwen_trace_role_row(
    role: str,
    traces: list[dict[str, Any]],
    token_keys: dict[str, str],
    usage: dict[str, Any],
) -> dict[str, Any]:
    token_key = token_keys.get(role, f"{role}_total_tokens")
    model_names = sorted({str(trace.get("model_name", "unknown")) for trace in traces})
    return {
        "provider_role": role,
        "model_name": model_names[0] if len(model_names) == 1 else ", ".join(model_names),
        "trace_count": len(traces),
        "live_trace_count": sum(1 for trace in traces if trace.get("is_live")),
        "input_token_estimate": sum(
            int(trace.get("input_token_estimate", 0) or 0) for trace in traces
        ),
        "output_item_count": sum(int(trace.get("output_item_count", 0) or 0) for trace in traces),
        "token_usage_key": token_key,
        "actual_tokens": int(usage.get(token_key, 0) or 0),
    }


def _qwen_trace_stages(
    role_summary: list[dict[str, Any]],
    compile_trace: dict[str, Any],
    downstream: dict[str, Any],
) -> list[dict[str, Any]]:
    roles = {role["provider_role"]: role for role in role_summary}
    return [
        {
            "id": "observe_memory_decisions",
            "label": "Observe memory decisions",
            "provider_role": "memory_decision",
            "model_work": "extract, classify, duplicate-check, and judge supersession",
            "trace_count": roles.get("memory_decision", {}).get("trace_count", 0),
        },
        {
            "id": "compile_embedding_retrieval",
            "label": "Compile embedding retrieval",
            "provider_role": "embedding",
            "model_work": "embed goal and active memory documents",
            "trace_count": roles.get("embedding", {}).get("trace_count", 0),
            "candidate_count": compile_trace.get("candidate_count", 0),
            "embedding_top_n_count": compile_trace.get("embedding_top_n_count", 0),
        },
        {
            "id": "compile_rerank",
            "label": "Compile rerank",
            "provider_role": "rerank",
            "model_work": "rerank embedding top-N candidates before budget selection",
            "trace_count": roles.get("rerank", {}).get("trace_count", 0),
            "selected_count": compile_trace.get("selected_count", 0),
        },
        {
            "id": "downstream_patch_generation",
            "label": "Downstream patch generation",
            "provider_role": "patch_generation",
            "model_work": (
                "stored live E2E trace records Qwen patch generation; local demo "
                "patch proof uses a deterministic context-keyed provider"
            ),
            "trace_count": roles.get("patch_generation", {}).get("trace_count", 0),
            "same_provider_contract": bool(downstream.get("same_provider_contract", False)),
            "used_gold_patch_variants": bool(downstream.get("used_gold_patch_variants", False)),
            "mode_note": (
                "stored live E2E uses Qwen patch generation; local demo uses a "
                "deterministic context-keyed patch provider"
            ),
        },
    ]


def _qwen_downstream_trace_summary(downstream: dict[str, Any]) -> str:
    baseline = downstream.get("baseline", {}).get("summary", {})
    recallpack = downstream.get("recallpack", {}).get("summary", {})
    if baseline or recallpack:
        baseline_passed = baseline.get("passed", 0)
        baseline_total = int(baseline.get("passed", 0) or 0) + int(baseline.get("failed", 0) or 0)
        recallpack_passed = recallpack.get("passed", 0)
        recallpack_total = int(recallpack.get("passed", 0) or 0) + int(
            recallpack.get("failed", 0) or 0
        )
        return (
            f"baseline {baseline_passed}/{baseline_total}; "
            f"RecallPack {recallpack_passed}/{recallpack_total}"
        )
    return "not run in local fake-provider demo"


def _variant_payload(variant_id: str, variant: Any) -> dict[str, Any]:
    labels = {
        "raw_full_history": "Raw full history",
        "embedding_top_k_rag": "Embedding top-N + rerank RAG",
        "recallpack": "RecallPack",
    }
    return {
        "id": variant_id,
        "label": labels.get(variant_id, variant_id),
        "selected_context": variant.selected_context,
        "metrics": variant.metrics,
        "downstream": variant.downstream,
        "compile_trace": variant.compile_trace,
    }


def _hero_memory_lifecycle() -> list[dict[str, str]]:
    return [
        {
            "id": "mem_retry_old",
            "status": "superseded",
            "source": "session-a:turn-001",
            "text": "Use three attempts with a fixed 100 ms delay.",
        },
        {
            "id": "mem_retry_current",
            "status": "active",
            "source": "session-a:turn-005",
            "text": "Use five attempts with exponential backoff.",
        },
        {
            "id": "mem_dependency_policy",
            "status": "active",
            "source": "session-a:turn-003",
            "text": "Keep retry behavior dependency-free.",
        },
    ]
