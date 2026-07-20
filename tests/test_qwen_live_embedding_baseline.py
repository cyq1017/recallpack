import importlib.util
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from recallpack.live_qwen_embedding_baseline import (
    build_live_qwen_embedding_baseline_preflight_report,
    build_live_qwen_embedding_baseline_report,
    write_live_qwen_embedding_baseline_preflight_report,
)
from recallpack.providers import RERANK_MODEL, TEXT_EMBEDDING_MODEL


ROOT = Path(__file__).resolve().parents[1]


class FakeHTTPResponse:
    def __init__(self, body):
        self._body = json.dumps(body).encode("utf-8")
        self.headers = {}

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
        self.requests.append(request)
        return self._responses.pop(0)


class LiveQwenEmbeddingBaselineTests(unittest.TestCase):
    def test_embedding_baseline_preflight_checks_real_provider_contract_without_credentials(self):
        report = build_live_qwen_embedding_baseline_preflight_report(
            fixture_root=ROOT / "fixtures" / "project-a",
            compatible_base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
            rerank_base_url="https://dashscope.aliyuncs.com/compatible-api/v1",
        )

        self.assertEqual(
            report["preflight_status"],
            "ready_for_live_embedding_baseline_rerun",
        )
        self.assertFalse(report["live_qwen_run"])
        self.assertFalse(report["network_calls_made"])
        self.assertEqual(
            report["model_names"],
            {"embedding": TEXT_EMBEDDING_MODEL, "rerank": RERANK_MODEL},
        )
        self.assertEqual(report["request_role_counts"], {"embedding": 13, "rerank": 1})
        self.assertEqual(report["retrieval_top_n"], 4)
        self.assertEqual(report["selection_top_k"], 2)
        self.assertEqual(
            report["expected_selected_sources"],
            ["session-a:turn-001", "session-a:turn-003"],
        )
        self.assertTrue(report["checks"]["real_embedding_endpoint_contract_ready"])
        self.assertTrue(report["checks"]["real_rerank_endpoint_contract_ready"])
        self.assertTrue(report["checks"]["stale_retry_selected_by_real_embedding_path"])
        self.assertEqual(report["expected_downstream_tests"], "1/3")
        self.assertNotIn("DASHSCOPE_API_KEY", json.dumps(report, sort_keys=True))
        self.assertNotIn("Use three attempts", json.dumps(report, sort_keys=True))
        self.assertNotIn("Do not add new dependencies", json.dumps(report, sort_keys=True))

    def test_live_embedding_baseline_report_uses_provider_embeddings_not_fixture_vectors(self):
        opener = RecordingOpener(_baseline_responses())

        report = build_live_qwen_embedding_baseline_report(
            fixture_root=ROOT / "fixtures" / "project-a",
            api_key="unit-secret",
            compatible_base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
            rerank_base_url="https://dashscope.aliyuncs.com/compatible-api/v1",
            opener=opener,
        )

        self.assertTrue(report["live_qwen_run"])
        self.assertEqual(report["live_status"], "live_embedding_baseline_passed")
        self.assertEqual(report["scenario"], "hero_real_embedding_raw_history_baseline")
        self.assertEqual(report["selected_sources"], ["session-a:turn-001", "session-a:turn-003"])
        self.assertTrue(report["checks"]["stale_retry_selected"])
        self.assertFalse(report["checks"]["active_retry_selected"])
        self.assertEqual(report["downstream_tests"], {"passed": 1, "failed": 2})
        self.assertEqual(len(opener.requests), 14)
        self.assertTrue(
            all(
                trace["deterministic_fallback_status"] == "live_qwen"
                for trace in report["provider_traces"]
            )
        )
        self.assertEqual(
            report["actual_qwen_token_usage"],
            {"embedding_total_tokens": 65, "rerank_total_tokens": 9},
        )
        self.assertNotIn("unit-secret", json.dumps(report, sort_keys=True))
        self.assertNotIn("Use three attempts", json.dumps(report, sort_keys=True))

    def test_write_embedding_baseline_preflight_report_creates_review_safe_json(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            target = Path(tmpdir) / "live-qwen-embedding-baseline-preflight.json"

            report = write_live_qwen_embedding_baseline_preflight_report(
                target=target,
                fixture_root=ROOT / "fixtures" / "project-a",
                compatible_base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
                rerank_base_url="https://dashscope.aliyuncs.com/compatible-api/v1",
            )
            written = target.read_text()

        self.assertEqual(
            report["preflight_status"],
            "ready_for_live_embedding_baseline_rerun",
        )
        self.assertIn('"ready_for_live_embedding_baseline_rerun"', written)
        self.assertIn('"network_calls_made": false', written)
        self.assertNotIn("DASHSCOPE_API_KEY", written)
        self.assertNotIn("Use five attempts", written)

    def test_live_embedding_baseline_tool_requires_explicit_approval_before_api_key(self):
        tool = _load_live_embedding_baseline_tool()

        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaisesRegex(SystemExit, "RECALLPACK_ENABLE_LIVE_QWEN=1"):
                tool.main()

        with patch.dict(os.environ, {"RECALLPACK_ENABLE_LIVE_QWEN": "1"}, clear=True):
            with self.assertRaisesRegex(
                SystemExit,
                "RECALLPACK_LIVE_QWEN_EMBEDDING_BASELINE_APPROVED=1",
            ):
                tool.main()

        with patch.dict(
            os.environ,
            {
                "RECALLPACK_ENABLE_LIVE_QWEN": "1",
                "RECALLPACK_LIVE_QWEN_EMBEDDING_BASELINE_APPROVED": "1",
            },
            clear=True,
        ):
            with self.assertRaisesRegex(SystemExit, "DASHSCOPE_API_KEY is required"):
                tool.main()

    def test_live_embedding_baseline_preflight_tool_does_not_require_credentials(self):
        tool = _load_live_embedding_baseline_preflight_tool()
        with tempfile.TemporaryDirectory() as tmpdir:
            target = Path(tmpdir) / "preflight.json"

            with patch.dict(
                os.environ,
                {"RECALLPACK_LIVE_QWEN_EMBEDDING_BASELINE_PREFLIGHT_PATH": str(target)},
                clear=True,
            ):
                tool.main()
            written = target.read_text()

        self.assertIn('"ready_for_live_embedding_baseline_rerun"', written)
        self.assertIn('"network_calls_made": false', written)
        self.assertNotIn("DASHSCOPE_API_KEY", written)


def _baseline_responses():
    responses = [_embedding_response("query-emb", [1.0, 0.0, 0.0], 5)]
    document_vectors = {
        "turn-001": [1.0, 0.0, 0.0],
        "turn-003": [0.95, 0.05, 0.0],
        "turn-005": [0.25, 0.9, 0.0],
        "default": [0.0, 0.0, 1.0],
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
        vector = document_vectors.get(event_id, document_vectors["default"])
        responses.append(_embedding_response(f"{event_id}-emb", vector, 5))
    responses.append(_rerank_response([0, 1, 2, 3], 9))
    return responses


def _embedding_response(request_id, vector, total_tokens):
    return FakeHTTPResponse(
        {
            "id": request_id,
            "model": TEXT_EMBEDDING_MODEL,
            "data": [{"embedding": vector}],
            "usage": {"total_tokens": total_tokens},
        }
    )


def _rerank_response(indexes, total_tokens):
    return FakeHTTPResponse(
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


def _load_live_embedding_baseline_tool():
    path = ROOT / "tools" / "run_live_qwen_embedding_baseline.py"
    spec = importlib.util.spec_from_file_location(
        "run_live_qwen_embedding_baseline",
        path,
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _load_live_embedding_baseline_preflight_tool():
    path = ROOT / "tools" / "build_live_qwen_embedding_baseline_preflight.py"
    spec = importlib.util.spec_from_file_location(
        "build_live_qwen_embedding_baseline_preflight",
        path,
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


if __name__ == "__main__":
    unittest.main()
