import json
import importlib.util
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from recallpack.live_qwen_e2e import (
    build_live_qwen_e2e_preflight_report,
    build_live_qwen_e2e_report,
    write_live_qwen_e2e_preflight_report,
    write_live_qwen_e2e_report,
)
from recallpack.providers import TEXT_MODEL


ROOT = Path(__file__).resolve().parents[1]


class FakeHTTPResponse:
    def __init__(self, body, headers=None):
        self._body = body.encode("utf-8")
        self.headers = headers or {}

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False


class RecordingOpener:
    def __init__(self, responses):
        self._responses = list(responses)
        self.requests = []

    def __call__(self, request, timeout):
        self.requests.append({"request": request, "timeout": timeout})
        return self._responses.pop(0)


class QwenLiveE2ETests(unittest.TestCase):
    def test_live_qwen_e2e_preflight_checks_sanitized_request_contract(self):
        report = build_live_qwen_e2e_preflight_report(
            fixture_root=ROOT / "fixtures" / "project-a",
            compatible_base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
            rerank_base_url="https://dashscope.aliyuncs.com/compatible-api/v1",
        )

        self.assertEqual(report["preflight_status"], "ready_for_live_e2e_rerun")
        self.assertFalse(report["live_qwen_run"])
        self.assertFalse(report["network_calls_made"])
        self.assertEqual(report["expected_selected_sources"], ["session-a:turn-005", "session-a:turn-003"])
        self.assertEqual(
            report["request_role_counts"],
            {"memory_decision": 12, "embedding": 29, "rerank": 2, "patch_generation": 2},
        )
        self.assertEqual(report["patch_generation_preflight"]["request_count"], 2)
        self.assertTrue(report["patch_generation_preflight"]["same_provider_contract"])
        self.assertTrue(report["patch_generation_preflight"]["all_tool_choice_function"])
        self.assertTrue(report["patch_generation_preflight"]["all_allowed_paths_present"])
        self.assertEqual(report["expected_downstream_tests"]["baseline"], "1/3")
        self.assertEqual(report["expected_downstream_tests"]["recallpack"], "3/3")
        contract = report["memory_decision_request_contract"]
        self.assertEqual(contract["request_count"], 12)
        self.assertTrue(contract["all_enable_thinking_false"])
        self.assertTrue(contract["all_tool_choice_function"])
        self.assertTrue(contract["all_structured_event_metadata"])
        self.assertTrue(contract["all_decision_policy_present"])
        self.assertTrue(contract["all_descriptive_tool_schema"])
        self.assertIn("session-a:turn-005", contract["source_refs_seen"])
        self.assertIn("session-a:turn-003", contract["source_refs_seen"])
        self.assertNotIn("unit-secret", str(report))
        self.assertNotIn("Use three attempts", str(report))
        self.assertNotIn("Use five attempts", str(report))
        self.assertNotIn("Do not add new dependencies", str(report))

    def test_projectodyssey_live_qwen_e2e_preflight_uses_source_backed_fixture_contract(self):
        report = build_live_qwen_e2e_preflight_report(
            fixture_root=ROOT / "fixtures" / "project-h-projectodyssey-jit",
            compatible_base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
            rerank_base_url="https://dashscope.aliyuncs.com/compatible-api/v1",
        )

        self.assertEqual(report["preflight_status"], "ready_for_live_e2e_rerun")
        self.assertFalse(report["live_qwen_run"])
        self.assertFalse(report["network_calls_made"])
        self.assertEqual(report["project_id"], "project-h-projectodyssey-jit")
        self.assertEqual(report["scenario"], "projectodyssey_observe_compile_preflight")
        self.assertEqual(
            report["expected_selected_sources"],
            ["session-h-current:turn-006", "session-h-history:turn-004"],
        )
        self.assertEqual(
            report["expected_baseline_selection"]["selected_sources"],
            ["session-h-history:turn-002", "session-h-history:turn-004"],
        )
        self.assertEqual(report["expected_downstream_tests"]["baseline"], "1/3")
        self.assertEqual(report["expected_downstream_tests"]["recallpack"], "3/3")
        self.assertEqual(
            report["request_role_counts"],
            {"memory_decision": 12, "embedding": 27, "rerank": 2, "patch_generation": 2},
        )
        self.assertTrue(report["checks"]["required_sources_selected"])
        self.assertTrue(report["checks"]["stale_sources_excluded"])
        contract = report["memory_decision_request_contract"]
        self.assertIn("session-h-current:turn-006", contract["source_refs_seen"])
        self.assertIn("session-h-history:turn-004", contract["source_refs_seen"])
        self.assertTrue(report["patch_generation_preflight"]["all_allowed_paths_present"])
        self.assertNotIn("unit-secret", str(report))
        self.assertNotIn("retry loops with three attempts", str(report))
        self.assertNotIn("Mojo JIT crashes are now real bugs", str(report))
        self.assertNotIn("Do not add new dependencies for CI", str(report))

    def test_write_live_qwen_e2e_preflight_report_creates_review_safe_json(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            target = Path(tmpdir) / "live-qwen-e2e-preflight.json"

            report = write_live_qwen_e2e_preflight_report(
                target=target,
                fixture_root=ROOT / "fixtures" / "project-a",
                compatible_base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
                rerank_base_url="https://dashscope.aliyuncs.com/compatible-api/v1",
            )
            written = target.read_text()

        self.assertEqual(report["preflight_status"], "ready_for_live_e2e_rerun")
        self.assertIn('"ready_for_live_e2e_rerun"', written)
        self.assertIn('"network_calls_made": false', written)
        self.assertNotIn("DASHSCOPE_API_KEY", written)
        self.assertNotIn("tool_arguments", written)
        self.assertNotIn("Use five attempts", written)

    def test_write_projectodyssey_live_qwen_e2e_preflight_report_creates_review_safe_json(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            target = Path(tmpdir) / "projectodyssey-live-qwen-e2e-preflight.json"

            report = write_live_qwen_e2e_preflight_report(
                target=target,
                fixture_root=ROOT / "fixtures" / "project-h-projectodyssey-jit",
                compatible_base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
                rerank_base_url="https://dashscope.aliyuncs.com/compatible-api/v1",
            )
            written = target.read_text()

        self.assertEqual(report["preflight_status"], "ready_for_live_e2e_rerun")
        self.assertIn('"project-h-projectodyssey-jit"', written)
        self.assertIn('"projectodyssey_observe_compile_preflight"', written)
        self.assertIn('"network_calls_made": false', written)
        self.assertNotIn("DASHSCOPE_API_KEY", written)
        self.assertNotIn("tool_arguments", written)
        self.assertNotIn("Mojo JIT crashes are now real bugs", written)

    def test_live_qwen_e2e_report_runs_observe_compile_lifecycle(self):
        opener = RecordingOpener(_hero_e2e_responses())

        report = build_live_qwen_e2e_report(
            fixture_root=ROOT / "fixtures" / "project-a",
            api_key="unit-secret",
            compatible_base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
            rerank_base_url="https://dashscope.aliyuncs.com/compatible-api/v1",
            opener=opener,
        )

        self.assertTrue(report["live_qwen_run"])
        self.assertEqual(report["live_status"], "live_e2e_passed")
        self.assertEqual(report["scenario"], "hero_observe_compile")
        self.assertEqual(report["observed_event_count"], 12)
        self.assertEqual(report["observe_status_counts"], {"200": 12})
        self.assertEqual(report["selected_sources"], ["session-a:turn-005", "session-a:turn-003"])
        self.assertTrue(report["checks"]["required_sources_selected"])
        self.assertTrue(report["checks"]["stale_sources_excluded"])
        self.assertTrue(report["checks"]["active_retry_selected"])
        self.assertTrue(report["checks"]["project_preference_selected"])
        self.assertTrue(report["checks"]["stale_retry_excluded"])
        self.assertTrue(report["checks"]["all_observe_events_completed"])
        self.assertLessEqual(report["pack_memory_segment_tokens"], 512)
        self.assertEqual(report["downstream_patch_generation"]["baseline"]["summary"], {"passed": 1, "failed": 2})
        self.assertEqual(report["downstream_patch_generation"]["recallpack"]["summary"], {"passed": 3, "failed": 0})
        self.assertTrue(report["downstream_patch_generation"]["same_provider_contract"])
        self.assertEqual(
            report["downstream_patch_generation"]["baseline"]["provider_role"],
            "patch_generation",
        )
        self.assertEqual(
            report["downstream_patch_generation"]["recallpack"]["provider_role"],
            "patch_generation",
        )
        self.assertFalse(report["downstream_patch_generation"]["used_gold_patch_variants"])
        self.assertEqual(len(opener.requests), 45)
        self.assertIn("run_completed_at", report)
        self.assertEqual(
            report["baseline_selection"]["context_source"],
            "live_embedding_top_n_rerank_raw_history",
        )
        self.assertEqual(
            report["baseline_selection"]["selected_sources"],
            ["session-a:turn-001", "session-a:turn-003"],
        )
        self.assertIn("baseline_downstream_fails", report["checks"])
        self.assertIn("baseline_downstream_reported", report["checks"])
        self.assertNotIn(
            "baseline_downstream_fails",
            report["live_status_required_checks"],
        )

        provider_roles = [trace["provider_role"] for trace in report["provider_traces"]]
        self.assertEqual(provider_roles.count("memory_decision"), 12)
        self.assertEqual(provider_roles.count("embedding"), 29)
        self.assertEqual(provider_roles.count("rerank"), 2)
        self.assertEqual(provider_roles.count("patch_generation"), 2)
        for trace in report["provider_traces"]:
            self.assertTrue(trace["is_live"])
            self.assertEqual(trace["deterministic_fallback_status"], "live_qwen")
            self.assertTrue(trace["request_id_present"])
            self.assertIn("request_id", trace)
        self.assertEqual(
            report["actual_qwen_token_usage"],
            {
                "memory_decision_total_tokens": 120,
                "embedding_total_tokens": 145,
                "rerank_total_tokens": 16,
                "patch_generation_total_tokens": 40,
            },
        )
        self.assertNotIn("unit-secret", str(report))
        self.assertNotIn("Use three attempts", str(report))

    def test_live_qwen_e2e_pass_status_does_not_require_baseline_failure(self):
        responses = _hero_e2e_responses(
            baseline_patch_files=_correct_retry_patch_files(),
        )
        opener = RecordingOpener(responses)

        report = build_live_qwen_e2e_report(
            fixture_root=ROOT / "fixtures" / "project-a",
            api_key="unit-secret",
            compatible_base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
            rerank_base_url="https://dashscope.aliyuncs.com/compatible-api/v1",
            opener=opener,
        )

        self.assertEqual(report["live_status"], "live_e2e_passed")
        self.assertFalse(report["checks"]["baseline_downstream_fails"])
        self.assertTrue(report["checks"]["baseline_downstream_reported"])
        self.assertEqual(
            report["downstream_patch_generation"]["baseline"]["summary"],
            {"passed": 3, "failed": 0},
        )
        self.assertNotIn(
            "baseline_downstream_fails",
            report["live_status_required_checks"],
        )

    def test_live_qwen_e2e_patch_generation_failure_payload_is_actionable(self):
        opener = RecordingOpener(
            _hero_e2e_responses(
                recallpack_patch_files=[
                    {"path": "README.md", "content": "not an allowed code path"}
                ],
            )
        )

        report = build_live_qwen_e2e_report(
            fixture_root=ROOT / "fixtures" / "project-a",
            api_key="unit-secret",
            compatible_base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
            rerank_base_url="https://dashscope.aliyuncs.com/compatible-api/v1",
            opener=opener,
        )

        recallpack = report["downstream_patch_generation"]["recallpack"]

        self.assertEqual(report["live_status"], "live_e2e_failed")
        self.assertFalse(recallpack["accepted"])
        self.assertEqual(recallpack["error"], "path_not_allowed")
        self.assertEqual(recallpack["output_paths"], ["README.md"])
        self.assertEqual(recallpack["source_file_paths"], ["src/retry.py", "pyproject.toml"])
        self.assertEqual(
            recallpack["selected_context_source_refs"],
            ["session-a:turn-005", "session-a:turn-003"],
        )
        self.assertNotIn("Use five attempts", json.dumps(report, sort_keys=True))
        self.assertNotIn("def retry", json.dumps(report, sort_keys=True))

    def test_write_live_qwen_e2e_report_creates_review_safe_json(self):
        opener = RecordingOpener(_hero_e2e_responses())
        with tempfile.TemporaryDirectory() as tmpdir:
            target = Path(tmpdir) / "live-qwen-e2e-trace.json"

            report = write_live_qwen_e2e_report(
                target=target,
                fixture_root=ROOT / "fixtures" / "project-a",
                api_key="unit-secret",
                compatible_base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
                rerank_base_url="https://dashscope.aliyuncs.com/compatible-api/v1",
                opener=opener,
            )
            written = target.read_text()

        self.assertEqual(report["live_status"], "live_e2e_passed")
        self.assertIn('"live_e2e_passed"', written)
        self.assertIn('"run_completed_at"', written)
        self.assertIn('"request_id"', written)
        self.assertIn('"selected_sources"', written)
        self.assertNotIn("unit-secret", written)
        self.assertNotIn("tool_arguments", written)
        self.assertNotIn("Use five attempts", written)

    def test_live_qwen_e2e_tool_requires_explicit_e2e_approval_before_api_key(self):
        tool = _load_live_e2e_tool()

        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaisesRegex(SystemExit, "RECALLPACK_ENABLE_LIVE_QWEN=1"):
                tool.main()

        with patch.dict(os.environ, {"RECALLPACK_ENABLE_LIVE_QWEN": "1"}, clear=True):
            with self.assertRaisesRegex(SystemExit, "RECALLPACK_LIVE_QWEN_E2E_APPROVED=1"):
                tool.main()

        with patch.dict(
            os.environ,
            {
                "RECALLPACK_ENABLE_LIVE_QWEN": "1",
                "RECALLPACK_LIVE_QWEN_E2E_APPROVED": "1",
            },
            clear=True,
        ):
            with self.assertRaisesRegex(SystemExit, "DASHSCOPE_API_KEY is required"):
                tool.main()

    def test_live_qwen_e2e_tool_writes_sanitized_failure_trace(self):
        tool = _load_live_e2e_tool()
        with tempfile.TemporaryDirectory() as tmpdir:
            target = Path(tmpdir) / "live-qwen-e2e-trace.json"
            with patch.dict(
                os.environ,
                {
                    "RECALLPACK_ENABLE_LIVE_QWEN": "1",
                    "RECALLPACK_LIVE_QWEN_E2E_APPROVED": "1",
                    "DASHSCOPE_API_KEY": "unit-secret",
                    "RECALLPACK_LIVE_QWEN_E2E_TRACE_PATH": str(target),
                },
                clear=True,
            ), patch.object(
                tool,
                "write_live_qwen_e2e_report",
                side_effect=RuntimeError("bad credential unit-secret"),
            ):
                with self.assertRaises(SystemExit) as caught:
                    tool.main()

            written = target.read_text()
            payload = json.loads(written)

        self.assertEqual(caught.exception.code, 1)
        self.assertEqual(payload["live_status"], "live_e2e_failed")
        self.assertTrue(payload["live_qwen_run"])
        self.assertEqual(payload["scenario"], "hero_observe_compile")
        self.assertEqual(payload["failure_kind"], "RuntimeError")
        self.assertIn("bad credential", payload["failure_summary"])
        self.assertNotIn("unit-secret", written)
        self.assertNotIn(tmpdir, written)
        self.assertEqual(payload["trace_artifact"], "live-qwen-e2e-trace.json")
        self.assertFalse(payload["credentials_recorded"])

    def test_live_qwen_e2e_tool_failure_trace_uses_target_fixture_identity(self):
        tool = _load_live_e2e_tool()
        with tempfile.TemporaryDirectory() as tmpdir:
            target = Path(tmpdir) / "projectodyssey-live-qwen-e2e-trace.json"
            with patch.dict(
                os.environ,
                {
                    "RECALLPACK_ENABLE_LIVE_QWEN": "1",
                    "RECALLPACK_LIVE_QWEN_E2E_APPROVED": "1",
                    "DASHSCOPE_API_KEY": "unit-secret",
                    "RECALLPACK_LIVE_QWEN_E2E_TRACE_PATH": str(target),
                    "RECALLPACK_LIVE_QWEN_E2E_FIXTURE": str(
                        ROOT / "fixtures" / "project-h-projectodyssey-jit"
                    ),
                },
                clear=True,
            ), patch.object(
                tool,
                "write_live_qwen_e2e_report",
                side_effect=RuntimeError("bad credential unit-secret"),
            ):
                with self.assertRaises(SystemExit) as caught:
                    tool.main()

            payload = json.loads(target.read_text())

        self.assertEqual(caught.exception.code, 1)
        self.assertEqual(payload["live_status"], "live_e2e_failed")
        self.assertEqual(payload["scenario"], "projectodyssey_observe_compile")
        self.assertEqual(payload["project_id"], "project-h-projectodyssey-jit")
        self.assertEqual(payload["fixture_root_name"], "project-h-projectodyssey-jit")
        self.assertIn("session-h-history:turn-002", payload["excluded_sources_checked"])
        self.assertNotIn("unit-secret", json.dumps(payload, sort_keys=True))

    def test_live_qwen_e2e_preflight_tool_does_not_require_credentials(self):
        tool = _load_live_e2e_preflight_tool()
        with tempfile.TemporaryDirectory() as tmpdir:
            target = Path(tmpdir) / "preflight.json"

            with patch.dict(os.environ, {"RECALLPACK_LIVE_QWEN_E2E_PREFLIGHT_PATH": str(target)}, clear=True):
                tool.main()
            written = target.read_text()

        self.assertIn('"ready_for_live_e2e_rerun"', written)
        self.assertIn('"network_calls_made": false', written)
        self.assertNotIn("DASHSCOPE_API_KEY", written)

    def test_live_qwen_e2e_preflight_tool_can_target_projectodyssey_without_credentials(self):
        tool = _load_live_e2e_preflight_tool()
        with tempfile.TemporaryDirectory() as tmpdir:
            target = Path(tmpdir) / "projectodyssey-preflight.json"

            with patch.dict(
                os.environ,
                {
                    "RECALLPACK_LIVE_QWEN_E2E_PREFLIGHT_PATH": str(target),
                    "RECALLPACK_LIVE_QWEN_E2E_FIXTURE": str(
                        ROOT / "fixtures" / "project-h-projectodyssey-jit"
                    ),
                },
                clear=True,
            ):
                tool.main()
            written = target.read_text()

        self.assertIn('"ready_for_live_e2e_rerun"', written)
        self.assertIn('"project-h-projectodyssey-jit"', written)
        self.assertIn('"network_calls_made": false', written)
        self.assertNotIn("DASHSCOPE_API_KEY", written)

    def test_checked_in_live_qwen_e2e_trace_uses_current_shipped_text_model(self):
        trace_path = ROOT / "docs" / "submission" / "live-qwen-e2e-trace.json"
        payload = json.loads(trace_path.read_text())

        self.assertEqual(payload["live_status"], "live_e2e_passed")
        text_roles = {
            "memory_decision",
            "patch_generation",
        }
        text_model_traces = [
            trace
            for trace in payload["provider_traces"]
            if trace["provider_role"] in text_roles
        ]
        self.assertGreater(len(text_model_traces), 0)
        self.assertTrue(
            all(trace["model_name"] == TEXT_MODEL for trace in text_model_traces)
        )
        self.assertNotIn("qwen-plus", json.dumps(payload, sort_keys=True))


def _hero_e2e_responses(baseline_patch_files=None, recallpack_patch_files=None):
    operations = [
        _write_decision("retry_policy", "Use three attempts with a fixed 100 ms delay.", "retry"),
        _no_op("non_memory_event"),
        _write_preference("dependency_policy", "Do not add new dependencies."),
        _no_op("non_memory_event"),
        _write_decision(
            "retry_policy",
            "Use five attempts with exponential backoff.",
            "retry",
            supersedes=[1],
        ),
        _no_op("non_memory_event"),
        _no_op("already_superseded"),
        _duplicate(1, "same_dependency_preference"),
        _no_op("non_memory_event"),
        _write_decision("auth_policy", "Use bearer token validation in auth.", "auth"),
        _no_op("non_memory_event"),
        _no_op("handoff_goal"),
    ]
    responses = []
    active_count = 0
    for index, operation in enumerate(operations):
        if active_count:
            responses.append(
                _embedding_response(
                    f"observe-{index + 1}-query-emb", [1.0, 0.0], 5
                )
            )
        responses.append(_chat_response(index=index + 1, operation=operation))
        if operation.get("operation") == "write":
            responses.append(
                _embedding_response(
                    f"observe-{index + 1}-document-emb",
                    [1.0, 0.0],
                    5,
                )
            )
            active_count += 1 - len(
                operation.get("supersedes_candidate_indexes", [])
            )
    responses.extend(
        [
            _embedding_response("query-emb", [1.0, 0.0], 5),
            _rerank_response([0, 1], 7),
            _embedding_response("raw-query-emb", [1.0, 0.0, 0.0], 5),
            *_raw_history_embedding_responses(),
            _rerank_response([0, 1, 2, 3], 9),
            _patch_generation_response(
                "baseline-patch",
                baseline_patch_files or _stale_retry_patch_files(),
                20,
            ),
            _patch_generation_response(
                "recallpack-patch",
                recallpack_patch_files or _correct_retry_patch_files(),
                20,
            ),
        ]
    )
    return responses


def _raw_history_embedding_responses():
    document_vectors = {
        "turn-001": [1.0, 0.0, 0.0],
        "turn-003": [0.95, 0.05, 0.0],
        "turn-005": [0.25, 0.9, 0.0],
    }
    return [
        _embedding_response(
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


def _stale_retry_patch_files():
    return [
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
    ]


def _correct_retry_patch_files():
    return [
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
    ]


def _load_live_e2e_tool():
    path = ROOT / "tools" / "run_live_qwen_e2e.py"
    spec = importlib.util.spec_from_file_location("run_live_qwen_e2e", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _load_live_e2e_preflight_tool():
    path = ROOT / "tools" / "build_live_qwen_e2e_preflight.py"
    spec = importlib.util.spec_from_file_location("build_live_qwen_e2e_preflight", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _chat_response(index, operation):
    return FakeHTTPResponse(
        json.dumps(
            {
                "id": f"chat-{index}",
                "model": TEXT_MODEL,
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
    )


def _embedding_response(request_id, vector, total_tokens):
    padded = [*vector, *([0.0] * (1024 - len(vector)))]
    return FakeHTTPResponse(
        json.dumps(
            {
                "id": request_id,
                "model": "text-embedding-v4",
                "data": [{"embedding": padded}],
                "usage": {"total_tokens": total_tokens},
            }
        )
    )


def _rerank_response(indexes, total_tokens):
    return FakeHTTPResponse(
        json.dumps(
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
    )


def _patch_generation_response(request_id, files, total_tokens):
    return FakeHTTPResponse(
        json.dumps(
            {
                "id": request_id,
                "model": TEXT_MODEL,
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
    )


def _no_op(reason):
    return {
        "operation": "no_op",
        "memory": None,
        "duplicate_of_candidate_index": None,
        "supersedes_candidate_indexes": [],
        "reason": reason,
    }


def _duplicate(index, reason):
    return {
        "operation": "duplicate",
        "memory": None,
        "duplicate_of_candidate_index": index,
        "supersedes_candidate_indexes": [],
        "reason": reason,
    }


def _write_decision(subject, text, component, supersedes=None):
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
        "reason": f"remember_{subject}",
    }


def _write_preference(subject, text):
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
        "reason": f"remember_{subject}",
    }


if __name__ == "__main__":
    unittest.main()
