import importlib.util
import json
import os
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from unittest.mock import patch

from recallpack.demo_server import RecallPackDemoHandler
from recallpack.storage import SqliteEventStore


ROOT = Path(__file__).resolve().parents[1]


def _load_judge_smoke_module():
    path = ROOT / "tools" / "judge_smoke.py"
    spec = importlib.util.spec_from_file_location("judge_smoke", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class JudgeSmokeTests(unittest.TestCase):
    def test_judge_smoke_verifies_demo_and_compile_contract(self):
        judge_smoke = _load_judge_smoke_module()
        RecallPackDemoHandler.project_root = ROOT
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "observe.sqlite3"
            with patch.dict(os.environ, {"RECALLPACK_SQLITE_PATH": str(db_path)}):
                server = HTTPServer(("127.0.0.1", 0), RecallPackDemoHandler)
                thread = threading.Thread(target=server.serve_forever, daemon=True)
                thread.start()
                try:
                    base_url = f"http://127.0.0.1:{server.server_port}"
                    result = judge_smoke.run_judge_smoke(base_url)
                    second_result = judge_smoke.run_judge_smoke(base_url)
                finally:
                    server.shutdown()
                    server.server_close()
                    thread.join(timeout=2)
            stored_memories = SqliteEventStore(db_path).active_memories("project-a")

        self.assertEqual(result["status"], "passed")
        self.assertEqual(second_result["status"], "passed")
        self.assertEqual(len(stored_memories), 3)
        self.assertEqual(
            result["health"],
            {
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
            },
        )
        self.assertEqual(result["api_demo"]["live_status"], "live_contract_passed")
        self.assertEqual(result["api_demo"]["live_qwen_e2e_status"], "live_e2e_passed")
        self.assertEqual(
            result["api_demo"]["fresh_m98_live_rerun_status"],
            "live_e2e_failed",
        )
        self.assertEqual(result["api_demo"]["fixture_count"], 8)
        self.assertEqual(
            result["api_demo"]["generalization_status"],
            "curated_lifecycle_regression_fixtures",
        )
        self.assertEqual(result["api_demo"]["baseline_downstream_tests"], "1/3")
        self.assertEqual(result["api_demo"]["recallpack_downstream_tests"], "3/3")
        self.assertEqual(result["api_demo"]["simulator_title"], "First-Run Handoff Simulator")
        self.assertEqual(result["api_demo"]["simulator_baseline_tests"], "1/3")
        self.assertEqual(result["api_demo"]["simulator_recallpack_tests"], "3/3")
        self.assertEqual(
            result["api_demo"]["retrieval_path"],
            ["embedding top-N", "qwen3-rerank", "512-token budget selector"],
        )
        self.assertEqual(
            result["api_demo"]["qwen_provider_roles"],
            ["embedding", "memory_decision", "rerank"],
        )
        self.assertEqual(
            result["compile"],
            {
                "includes_active_decision": True,
                "includes_project_preference": True,
                "excludes_stale_decision": True,
                "contract_trace_is_fake": True,
                "contract_top_n_is_twenty": True,
                "contract_rerank_executed": True,
            },
        )
        self.assertEqual(
            result["seed"],
            {
                "old_decision_written": True,
                "preference_written": True,
                "active_decision_written": True,
            },
        )
        self.assertEqual(result["observe"]["operation"], "duplicate")
        self.assertEqual(result["observe"]["completed_lifecycle_operation"], True)
        self.assertEqual(result["observe"]["memory_type"], None)
        self.assertEqual(result["observe"]["component"], None)
        self.assertEqual(result["observe"]["contract_provider_mode_fake"], True)
        self.assertEqual(result["observe"]["contract_request_id_present"], True)
        self.assertTrue(result["observe"]["source_ref"].startswith("judge-smoke-"))
        self.assertNotEqual(
            result["observe"]["source_ref"],
            second_result["observe"]["source_ref"],
        )

    def test_judge_smoke_fails_when_live_qwen_status_is_not_passed(self):
        judge_smoke = _load_judge_smoke_module()

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                if self.path == "/":
                    self._write("RecallPack")
                    return
                if self.path == "/api/demo":
                    self._write_json(
                        {
                            "hero_story": {
                                "baseline": {
                                    "test_summary": {"passed": 1, "failed": 2, "total": 3}
                                },
                                "recallpack": {
                                    "test_summary": {"passed": 3, "failed": 0, "total": 3}
                                },
                                "retrieval_path": [
                                    "embedding top-N",
                                    "qwen3-rerank",
                                    "512-token budget selector",
                                ],
                            },
                            "evaluate": {
                                "generalization_fixtures": {
                                    "fixture_count": 8,
                                    "status": "curated_lifecycle_regression_fixtures",
                                }
                            },
                            "qwen_load_bearing": {
                                "live_status": "gated_not_run",
                                "provider_traces": [
                                    {"provider_role": "memory_decision"},
                                    {"provider_role": "embedding"},
                                    {"provider_role": "rerank"},
                                ],
                            },
                        }
                    )
                    return
                if self.path == "/api/health":
                    self._write_json(
                        {
                            "status": "ok",
                            "track": "MemoryAgent",
                            "credential_required_for_local_demo": False,
                            "qwen": {
                                "live_status": "live_contract_passed",
                                "provider_roles": [
                                    "embedding",
                                    "memory_decision",
                                    "rerank",
                                ],
                            },
                            "proof": {
                                "fixture_count": 8,
                                "baseline_downstream_tests": "1/3",
                                "recallpack_downstream_tests": "3/3",
                            },
                        }
                    )
                    return
                self.send_error(404)

            def do_POST(self):
                if self.path == "/observe":
                    self._write_json(
                        {
                            "final_result": {
                                "operation": "write",
                                "memory": {"type": "decision", "component": "retry"},
                            }
                        }
                    )
                    return
                if self.path == "/compile":
                    self._write_json(
                        {
                            "pack": [
                                "session-a:turn-005",
                                "session-a:turn-003",
                            ]
                        }
                    )
                    return
                self.send_error(404)

            def log_message(self, format, *args):
                return

            def _write(self, body: str):
                self.send_response(200)
                self.end_headers()
                self.wfile.write(body.encode("utf-8"))

            def _write_json(self, payload):
                self.send_response(200)
                self.send_header("content-type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps(payload).encode("utf-8"))

        server = HTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with self.assertRaisesRegex(AssertionError, "GET /api/health smoke failed"):
                judge_smoke.run_judge_smoke(f"http://127.0.0.1:{server.server_port}")
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)


if __name__ == "__main__":
    unittest.main()
