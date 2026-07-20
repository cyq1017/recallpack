from __future__ import annotations

import argparse
import json
import uuid
from typing import Any
from urllib.request import Request, urlopen


def run_judge_smoke(base_url: str, timeout: float = 5.0) -> dict[str, Any]:
    root = base_url.rstrip("/")
    index_body = _get_text(f"{root}/", timeout)
    if "RecallPack" not in index_body:
        raise AssertionError("GET / did not return the RecallPack shell")

    health = _get_json(f"{root}/api/health", timeout)
    health_checks = {
        "status": health.get("status"),
        "track": health.get("track"),
        "live_status": (health.get("qwen") or {}).get("live_status"),
        "live_qwen_e2e_status": (health.get("qwen") or {}).get(
            "live_qwen_e2e_status"
        ),
        "fresh_m98_live_rerun_status": (health.get("qwen") or {}).get(
            "fresh_m98_live_rerun_status"
        ),
        "fixture_count": (health.get("proof") or {}).get("fixture_count"),
        "baseline_downstream_tests": (health.get("proof") or {}).get(
            "baseline_downstream_tests"
        ),
        "recallpack_downstream_tests": (health.get("proof") or {}).get(
            "recallpack_downstream_tests"
        ),
        "qwen_provider_roles": (health.get("qwen") or {}).get("provider_roles"),
        "credential_required_for_local_demo": health.get(
            "credential_required_for_local_demo"
        ),
    }
    expected_health = {
        "status": "ok",
        "track": "MemoryAgent",
        "live_status": "live_contract_passed",
        "live_qwen_e2e_status": "live_e2e_passed",
        "fresh_m98_live_rerun_status": "live_e2e_failed",
        "fixture_count": 8,
        "baseline_downstream_tests": "1/3",
        "recallpack_downstream_tests": "3/3",
        "qwen_provider_roles": ["embedding", "memory_decision", "rerank"],
        "credential_required_for_local_demo": False,
    }
    if health_checks != expected_health:
        raise AssertionError(f"GET /api/health smoke failed: {health_checks}")

    demo = _get_json(f"{root}/api/demo", timeout)
    generalization = demo["evaluate"]["generalization_fixtures"]
    qwen = demo["qwen_load_bearing"]
    hero_story = demo["hero_story"]
    simulator = demo.get("handoff_simulator") or {}
    simulator_baseline = simulator.get("baseline") or {}
    simulator_recallpack = simulator.get("recallpack") or {}
    qwen_roles = sorted(
        {trace["provider_role"] for trace in qwen.get("provider_traces", [])}
    )
    api_demo_checks = {
        "live_status": qwen["live_status"],
        "live_qwen_e2e_status": qwen.get("live_qwen_e2e_status"),
        "fresh_m98_live_rerun_status": qwen.get("fresh_m98_live_rerun_status"),
        "fixture_count": generalization["fixture_count"],
        "generalization_status": generalization["status"],
        "baseline_downstream_tests": _test_ratio(hero_story["baseline"]["test_summary"]),
        "recallpack_downstream_tests": _test_ratio(hero_story["recallpack"]["test_summary"]),
        "simulator_title": simulator.get("title"),
        "simulator_baseline_tests": simulator_baseline.get("hidden_tests"),
        "simulator_recallpack_tests": simulator_recallpack.get("hidden_tests"),
        "retrieval_path": hero_story["retrieval_path"],
        "qwen_provider_roles": qwen_roles,
    }
    expected_api_demo = {
        "live_status": "live_contract_passed",
        "live_qwen_e2e_status": "live_e2e_passed",
        "fresh_m98_live_rerun_status": "live_e2e_failed",
        "fixture_count": 8,
        "generalization_status": "curated_lifecycle_regression_fixtures",
        "baseline_downstream_tests": "1/3",
        "recallpack_downstream_tests": "3/3",
        "simulator_title": "First-Run Handoff Simulator",
        "simulator_baseline_tests": "1/3",
        "simulator_recallpack_tests": "3/3",
        "retrieval_path": [
            "embedding top-N",
            "qwen3-rerank",
            "512-token budget selector",
        ],
        "qwen_provider_roles": ["embedding", "memory_decision", "rerank"],
    }
    if {key: api_demo_checks.get(key) for key in expected_api_demo} != expected_api_demo:
        raise AssertionError(f"GET /api/demo smoke failed: {api_demo_checks}")

    seed_checks = _seed_compile_fixture(root, timeout)

    compile_payload = _post_json(
        f"{root}/compile",
        {
            "project_id": "project-a",
            "goal": "Update the retry helper to the current project policy.",
            "component": "retry",
            "budget_tokens": 512,
        },
        timeout,
    )
    compile_text = json.dumps(compile_payload, sort_keys=True)
    compile_checks = {
        "includes_active_decision": "session-a:turn-005" in compile_text,
        "includes_project_preference": "session-a:turn-003" in compile_text,
        "excludes_stale_decision": "session-a:turn-001" not in compile_text,
        "contract_trace_is_fake": (
            (compile_payload.get("trace") or {}).get("provider_mode") == "fake"
        ),
        "contract_top_n_is_twenty": (
            (compile_payload.get("trace") or {}).get("embedding_top_n") == 20
        ),
        "contract_rerank_executed": (
            (compile_payload.get("trace") or {}).get("rerank_input_count", 0) > 0
        ),
    }
    if not all(compile_checks.values()):
        raise AssertionError(f"POST /compile smoke failed: {compile_checks}")

    observe_session_id = f"judge-smoke-{uuid.uuid4().hex[:12]}"
    observe_payload = _post_json(
        f"{root}/observe",
        {
            "project_id": "project-a",
            "session_id": observe_session_id,
            "event_id": "turn-010",
            "sequence_no": 1,
            "actor": "user",
            "kind": "message",
            "observed_at": "2026-06-24T00:00:00Z",
            "text": "Use bearer token validation in auth.",
        },
        timeout,
    )
    observe_memory = (observe_payload.get("final_result") or {}).get("memory") or {}
    observe_operation = (observe_payload.get("final_result") or {}).get("operation")
    observe_trace = observe_payload.get("trace") or {}
    observe_checks = {
        "operation": observe_operation,
        "completed_lifecycle_operation": observe_operation in {"write", "duplicate"},
        "memory_type": observe_memory.get("type"),
        "component": observe_memory.get("component"),
        "source_ref": (observe_payload.get("event") or {}).get("session_id"),
        "source_ref_matches_session": (
            (observe_payload.get("event") or {}).get("session_id")
            == observe_session_id
        ),
        "contract_provider_mode_fake": observe_trace.get("provider_mode") == "fake",
        "contract_request_id_present": observe_trace.get("request_id_present") is True,
    }
    expected_observe = {
        "completed_lifecycle_operation": True,
        "source_ref_matches_session": True,
        "contract_provider_mode_fake": True,
        "contract_request_id_present": True,
    }
    if {key: observe_checks.get(key) for key in expected_observe} != expected_observe:
        raise AssertionError(f"POST /observe smoke failed: {observe_checks}")

    return {
        "status": "passed",
        "base_url": root,
        "index": {"contains_recallpack_shell": True},
        "health": health_checks,
        "api_demo": api_demo_checks,
        "seed": seed_checks,
        "observe": observe_checks,
        "compile": compile_checks,
    }


def _seed_compile_fixture(root: str, timeout: float) -> dict[str, bool]:
    events = [
        (
            "turn-001",
            1,
            "user",
            "Use three attempts with a fixed 100 ms delay in the retry helper.",
        ),
        ("turn-002", 2, "assistant", "I can inspect retry.py and the public retry tests."),
        ("turn-003", 3, "user", "For this project, keep retry behavior dependency-free."),
        (
            "turn-004",
            4,
            "tool",
            "The last retry test failed because rate limits lasted longer than 300 ms.",
        ),
        (
            "turn-005",
            5,
            "user",
            "After the rate-limit failures, use five attempts with exponential backoff in the retry helper.",
        ),
        (
            "turn-006",
            6,
            "assistant",
            "I will keep the retry patch focused on the retry helper.",
        ),
        (
            "turn-007",
            7,
            "user",
            "That retry policy update replaces the earlier fixed-delay retry decision.",
        ),
        ("turn-008", 8, "user", "Do not change pyproject.toml for this retry change."),
        (
            "turn-009",
            9,
            "assistant",
            "I can prepare a patch that edits only src/retry.py if no dependency change is needed.",
        ),
        (
            "turn-010",
            10,
            "user",
            "Auth uses bearer token validation; it is not part of the retry task.",
        ),
        ("turn-011", 11, "user", "Cache cleanup can wait until after the retry work."),
        (
            "turn-012",
            12,
            "user",
            "Current handoff task: update the retry helper to the current project policy.",
        ),
    ]
    observed_operations: dict[str, str | None] = {}
    for event_id, sequence_no, actor, text in events:
        payload = _post_json(
            f"{root}/observe",
            {
                "project_id": "project-a",
                "session_id": "session-a",
                "event_id": event_id,
                "sequence_no": sequence_no,
                "actor": actor,
                "kind": "message",
                "observed_at": f"2026-06-24T00:{sequence_no - 1:02d}:00Z",
                "text": text,
            },
            timeout,
        )
        observed_operations[event_id] = (payload.get("final_result") or {}).get(
            "operation"
        )
    checks = {
        "old_decision_written": observed_operations.get("turn-001") == "write",
        "preference_written": observed_operations.get("turn-003") == "write",
        "active_decision_written": observed_operations.get("turn-005") == "write",
    }
    if not all(checks.values()):
        raise AssertionError(f"POST /observe fixture seed failed: {checks}")
    return checks


def _get_text(url: str, timeout: float) -> str:
    with urlopen(url, timeout=timeout) as response:
        return response.read().decode("utf-8")


def _get_json(url: str, timeout: float) -> dict[str, Any]:
    return json.loads(_get_text(url, timeout))


def _post_json(url: str, payload: dict[str, Any], timeout: float) -> dict[str, Any]:
    request = Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"content-type": "application/json"},
        method="POST",
    )
    with urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def _test_ratio(summary: dict[str, int]) -> str:
    return f"{summary['passed']}/{summary['total']}"


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://127.0.0.1:8789")
    parser.add_argument("--timeout", type=float, default=5.0)
    args = parser.parse_args(argv)
    print(json.dumps(run_judge_smoke(args.url, args.timeout), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
