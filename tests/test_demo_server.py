from concurrent.futures import ThreadPoolExecutor
import json
import os
import sqlite3
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

import yaml
from jsonschema import Draft202012Validator, FormatChecker

from recallpack.artifacts import validate_compile_bundle_v4
from recallpack.demo import discover_secondary_hero_fixture_roots
from recallpack.demo_server import (
    build_component_registry,
    create_demo_server,
    create_runtime_composition,
    handle_demo_request,
)
from recallpack.observe import ObserveRequest, RetryableObserveError
from recallpack.storage import SqliteEventStore


ROOT = Path(__file__).resolve().parents[1]
CONTRACT_ROOT = ROOT / "specs" / "001-recallpack-v4" / "contracts"


def contract_errors(document_name, schema_name, payload):
    document = yaml.safe_load((CONTRACT_ROOT / document_name).read_text())
    wrapper = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "components": document["components"],
        "$ref": f"#/components/schemas/{schema_name}",
    }
    return list(
        Draft202012Validator(
            wrapper,
            format_checker=FormatChecker(),
        ).iter_errors(payload)
    )


class Utf8Tokenizer:
    def count(self, text):
        return len(text.encode("utf-8"))


class RetryableNetworkDecider:
    traces = []

    def decide_memory_operation(self, request, candidates):
        raise RetryableObserveError("temporary network failure")


class DemoServerTests(unittest.TestCase):
    def setUp(self):
        self.tokenizer_patch = patch(
            "recallpack.budget.default_tokenizer",
            return_value=Utf8Tokenizer(),
        )
        self.tokenizer_patch.start()

    def tearDown(self):
        self.tokenizer_patch.stop()

    def test_demo_fixture_discovery_excludes_v4_repo_snapshot_only_fixtures(self):
        roots = discover_secondary_hero_fixture_roots(ROOT)

        self.assertEqual(
            [root.name for root in roots],
            [
                "project-b",
                "project-c",
                "project-d",
                "project-e",
                "project-f-realistic",
                "project-g-auth-mode",
                "project-h-projectodyssey-jit",
            ],
        )
        self.assertNotIn("project-i-deepagents-package", {root.name for root in roots})
        self.assertNotIn("project-j-graphiti-backend", {root.name for root in roots})

    def test_default_and_extended_component_registry_is_validated_and_immutable(self):
        default_registry = build_component_registry(None)
        extended_registry = build_component_registry(" worker_pool, ,api_client ")

        self.assertEqual(
            default_registry.values,
            ("retry", "auth", "cache", "config"),
        )
        self.assertEqual(
            extended_registry.values,
            ("retry", "auth", "cache", "config", "worker_pool", "api_client"),
        )
        self.assertIn("worker_pool", extended_registry)
        with self.assertRaises(AttributeError):
            extended_registry.add("mutable")
        with self.assertRaises(AttributeError):
            extended_registry.values = ("mutable",)

    def test_component_registry_rejects_invalid_duplicate_and_oversized_values(self):
        invalid_values = [
            ("Retry", "invalid_component_name"),
            ("retry", "duplicate_component"),
            ("worker,worker", "duplicate_component"),
            (",".join(f"component_{index}" for index in range(61)), "component_limit"),
            ("x" * 4097, "component_bytes_limit"),
        ]

        for configured, error in invalid_values:
            with self.subTest(error=error):
                with self.assertRaisesRegex(ValueError, error):
                    build_component_registry(configured)

    def test_runtime_composition_injects_one_registry_into_all_component_consumers(self):
        registry = build_component_registry("worker_pool")
        composition = create_runtime_composition(registry)
        observe_runtime = composition.create_observe_runtime(
            store=object(),
            decider=object(),
        )
        compile_service = composition.create_compile_service(
            store=object(),
            ranker=object(),
            embedding_provider=object(),
        )

        self.assertIs(observe_runtime._components, registry)
        self.assertIs(compile_service._components, registry)
        self.assertIs(composition.demo_components, registry)
        self.assertIs(composition.evaluator_components, registry)

    def test_create_demo_server_uses_threaded_http_server(self):
        composition = create_runtime_composition(build_component_registry(None))
        with patch.object(ThreadingHTTPServer, "server_bind"), patch.object(
            ThreadingHTTPServer,
            "server_activate",
        ):
            server = create_demo_server("127.0.0.1", 0, ROOT, composition=composition)
        try:
            self.assertIsInstance(server, ThreadingHTTPServer)
            self.assertEqual(server.RequestHandlerClass.project_root, ROOT)
            self.assertIs(server.RequestHandlerClass.runtime_composition, composition)
        finally:
            server.server_close()

    def test_multiple_servers_keep_root_and_composition_instance_local(self):
        first_composition = create_runtime_composition(build_component_registry(None))
        second_composition = create_runtime_composition(
            build_component_registry("worker_pool")
        )
        second_root = ROOT / "fixtures" / "project-a"
        with patch.object(ThreadingHTTPServer, "server_bind"), patch.object(
            ThreadingHTTPServer,
            "server_activate",
        ):
            first_server = create_demo_server(
                "127.0.0.1", 0, ROOT, composition=first_composition
            )
            second_server = create_demo_server(
                "127.0.0.1", 0, second_root, composition=second_composition
            )
        try:
            self.assertIsNot(
                first_server.RequestHandlerClass,
                second_server.RequestHandlerClass,
            )
            self.assertEqual(first_server.RequestHandlerClass.project_root, ROOT)
            self.assertEqual(second_server.RequestHandlerClass.project_root, second_root)
            self.assertIs(
                first_server.RequestHandlerClass.runtime_composition,
                first_composition,
            )
            self.assertIs(
                second_server.RequestHandlerClass.runtime_composition,
                second_composition,
            )
        finally:
            first_server.server_close()
            second_server.server_close()

    def test_get_api_demo_returns_demo_payload(self):
        response = handle_demo_request("GET", "/api/demo", b"", ROOT)
        payload = json.loads(response.body.decode("utf-8"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.headers["content-type"],
            "application/json; charset=utf-8",
        )
        self.assertEqual(payload["title"], "RecallPack")
        self.assertEqual(payload["evaluate"]["micro_suite"]["case_count"], 32)
        self.assertEqual(payload["hero_story"]["live_qwen_status"], "live_contract_passed")
        self.assertEqual(
            payload["qwen_load_bearing"]["standalone_contract_status"],
            "live_contract_passed",
        )
        self.assertEqual(
            payload["qwen_load_bearing"]["live_qwen_e2e_status"],
            "live_e2e_passed",
        )
        self.assertEqual(
            payload["qwen_load_bearing"]["stored_live_qwen_e2e_status"],
            "live_e2e_passed",
        )
        self.assertEqual(
            payload["qwen_load_bearing"]["fresh_m98_live_rerun_status"],
            "live_e2e_failed",
        )
        self.assertEqual(
            payload["qwen_load_bearing"]["projectodyssey_live_e2e_status"],
            "live_e2e_passed",
        )
        self.assertIn("2/3", payload["qwen_load_bearing"]["fresh_m98_live_rerun_summary"])
        self.assertIn(
            "RecallPack 3/3",
            payload["qwen_load_bearing"]["projectodyssey_live_e2e_summary"],
        )
        self.assertEqual(
            payload["handoff_simulator"]["qwen_boundary"]["first_screen_lines"],
            [
                "Standalone Qwen API smoke: passed",
                "Stored live provider-path E2E: one pass; fresh rerun failed",
                "ProjectOdyssey live E2E: passed",
                "Lifecycle filtering: held in stored live runs",
            ],
        )
        self.assertEqual(
            payload["handoff_replay"]["steps"][1]["result"],
            "wrong_retry_patch",
        )
        self.assertEqual(payload["handoff_replay"]["steps"][1]["hidden_tests"], "1/3")
        self.assertEqual(payload["handoff_replay"]["steps"][3]["hidden_tests"], "3/3")
        self.assertEqual(
            payload["qwen_load_bearing"]["actual_qwen_token_usage"],
            {
                "embedding_total_tokens": 20,
                "memory_decision_total_tokens": 301,
                "rerank_total_tokens": 29,
            },
        )

    def test_get_api_health_returns_compact_readiness_summary(self):
        response = handle_demo_request("GET", "/api/health", b"", ROOT)
        payload = json.loads(response.body.decode("utf-8"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(payload["status"], "ok")
        self.assertEqual(payload["project"], "RecallPack")
        self.assertEqual(payload["track"], "MemoryAgent")
        self.assertFalse(payload["credential_required_for_local_demo"])
        self.assertEqual(payload["qwen"]["live_status"], "live_contract_passed")
        self.assertEqual(payload["qwen"]["live_qwen_e2e_status"], "live_e2e_passed")
        self.assertEqual(
            payload["qwen"]["stored_live_qwen_e2e_status"],
            "live_e2e_passed",
        )
        self.assertEqual(
            payload["qwen"]["fresh_m98_live_rerun_status"],
            "live_e2e_failed",
        )
        self.assertEqual(
            payload["qwen"]["projectodyssey_live_e2e_status"],
            "live_e2e_passed",
        )
        self.assertEqual(
            payload["qwen"]["provider_roles"],
            ["embedding", "memory_decision", "rerank"],
        )
        self.assertEqual(payload["proof"]["fixture_count"], 8)
        self.assertEqual(payload["proof"]["baseline_downstream_tests"], "1/3")
        self.assertEqual(payload["proof"]["recallpack_downstream_tests"], "3/3")
        self.assertEqual(
            payload["proof"]["local_patch_generation_mode"],
            "deterministic_context_keyed_patch_provider",
        )
        self.assertEqual(
            payload["proof"]["local_baseline_retrieval_mode"],
            "keyword_scored_fake_embedding_rerank",
        )
        self.assertIn(
            "stored sanitized one-run trace",
            payload["qwen"]["evidence_mode"],
        )
        self.assertEqual(
            payload["proof"]["retrieval_path"],
            ["embedding top-N", "qwen3-rerank", "512-token budget selector"],
        )
        self.assertEqual(payload["runtime"]["deterministic_runtime"], True)

    def test_concurrent_health_requests_use_isolated_evaluator_turnstiles(self):
        barrier = threading.Barrier(2)

        def request_health():
            barrier.wait()
            return handle_demo_request("GET", "/api/health", b"", ROOT)

        with ThreadPoolExecutor(max_workers=2) as executor:
            responses = list(executor.map(lambda _: request_health(), range(2)))

        self.assertEqual([200, 200], [response.status_code for response in responses])
        self.assertEqual(
            ["ok", "ok"],
            [json.loads(response.body)["status"] for response in responses],
        )

    def test_post_compile_returns_fixture_backed_pack(self):
        body = json.dumps(
            {
                "project_id": "project-a",
                "goal": "Update the retry helper to the current project policy.",
                "component": "retry",
                "budget_tokens": 512,
            }
        ).encode("utf-8")
        with patch.dict(os.environ, {"RECALLPACK_SQLITE_PATH": ""}):
            response = handle_demo_request("POST", "/compile", body, ROOT)
        payload = json.loads(response.body.decode("utf-8"))
        selected_sources = {
            memory["source_ref"] for memory in payload["pack"]["memories"]
        }

        self.assertEqual(response.status_code, 200)
        self.assertLessEqual(payload["exact_token_count"], 512)
        self.assertIn("session-a:turn-005", selected_sources)
        self.assertNotIn("session-a:turn-001", selected_sources)
        self.assertEqual(payload["trace"]["embedding_top_n"], 20)
        self.assertEqual(payload["trace"]["rerank_input_count"], 2)
        self.assertEqual(payload["trace"]["provider_mode"], "fake")

    def test_post_compile_reports_provider_mode_without_internal_trace_fields(self):
        body = json.dumps(
            {
                "project_id": "project-a",
                "goal": "Update the retry helper to the current project policy.",
                "component": "retry",
                "budget_tokens": 512,
            }
        ).encode("utf-8")
        with patch.dict(os.environ, {"RECALLPACK_SQLITE_PATH": ""}):
            response = handle_demo_request("POST", "/compile", body, ROOT)
        payload = json.loads(response.body.decode("utf-8"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            set(payload["trace"]),
            {
                "memory_snapshot_seq",
                "active_candidate_count",
                "embedding_top_n",
                "rerank_input_count",
                "selected_count",
                "omitted_count",
                "provider_mode",
            },
        )
        self.assertEqual(payload["trace"]["provider_mode"], "fake")

    def test_post_compile_reads_memories_written_by_prior_http_observe(self):
        observe_body = json.dumps(
            {
                "project_id": "project-a",
                "session_id": "shared-session-a",
                "event_id": "turn-001",
                "sequence_no": 1,
                "actor": "user",
                "kind": "message",
                "observed_at": "2026-06-24T00:00:00Z",
                "text": "Use three attempts with a fixed 100 ms delay in the retry helper.",
            }
        ).encode("utf-8")
        compile_body = json.dumps(
            {
                "project_id": "project-a",
                "goal": "Update the retry helper to the current project policy.",
                "component": "retry",
                "budget_tokens": 512,
            }
        ).encode("utf-8")

        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "shared.sqlite3"
            with patch.dict(os.environ, {"RECALLPACK_SQLITE_PATH": str(db_path)}):
                observe = handle_demo_request("POST", "/observe", observe_body, ROOT)
                compile_response = handle_demo_request("POST", "/compile", compile_body, ROOT)

        observe_payload = json.loads(observe.body.decode("utf-8"))
        compile_payload = json.loads(compile_response.body.decode("utf-8"))
        selected_sources = {
            memory["source_ref"] for memory in compile_payload["pack"]["memories"]
        }

        self.assertEqual(observe.status_code, 200)
        self.assertEqual(observe_payload["final_result"]["operation"], "write")
        self.assertEqual(compile_response.status_code, 200)
        self.assertIn("shared-session-a:turn-001", selected_sources)
        self.assertEqual(compile_payload["trace"]["active_candidate_count"], 1)
        self.assertEqual(compile_payload["trace"]["provider_mode"], "fake")

    def test_post_compile_accepts_fresh_generic_project_without_source_edits(self):
        body = json.dumps(
            {
                "project_id": "fresh-generic-project",
                "goal": "Update retry behavior.",
                "component": "retry",
                "budget_tokens": 512,
            }
        ).encode("utf-8")
        with tempfile.TemporaryDirectory() as tmp:
            with patch.dict(
                os.environ,
                {
                    "RECALLPACK_SQLITE_PATH": str(Path(tmp) / "fresh.sqlite3"),
                    "RECALLPACK_ARTIFACT_ROOT": str(Path(tmp) / "artifacts"),
                },
            ):
                response = handle_demo_request("POST", "/compile", body, ROOT)
        payload = json.loads(response.body.decode("utf-8"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(payload["status_code"], 200)
        self.assertEqual(payload["pack"], {"memories": []})
        self.assertEqual(payload["trace"]["active_candidate_count"], 0)
        self.assertEqual(payload["trace"]["rerank_input_count"], 0)
        self.assertEqual(payload["trace"]["provider_mode"], "fake")
        self.assertEqual(
            [payload["artifacts"][key]["name"] for key in (
                "recallpack_json",
                "pack_md",
                "trace_json",
            )],
            ["recallpack.json", "PACK.md", "trace.json"],
        )

    def test_fresh_project_two_session_observe_compile_http_walking_skeleton(self):
        with tempfile.TemporaryDirectory() as tmp:
            project_id = f"judge-{Path(tmp).name}"
            db_path = Path(tmp) / "walking-skeleton.sqlite3"
            artifact_root = Path(tmp) / "artifacts"
            events = [
                {
                    "project_id": project_id,
                    "session_id": "session-one",
                    "event_id": "turn-001",
                    "sequence_no": 1,
                    "actor": "user",
                    "kind": "message",
                    "observed_at": "2026-07-10T00:00:00Z",
                    "text": "For retry, use three attempts with a fixed 100 ms delay.",
                },
                {
                    "project_id": project_id,
                    "session_id": "session-one",
                    "event_id": "turn-002",
                    "sequence_no": 2,
                    "actor": "user",
                    "kind": "message",
                    "observed_at": "2026-07-10T00:01:00Z",
                    "text": "For this project, do not add new dependencies.",
                },
                {
                    "project_id": project_id,
                    "session_id": "session-two",
                    "event_id": "turn-001",
                    "sequence_no": 1,
                    "actor": "user",
                    "kind": "message",
                    "observed_at": "2026-07-10T00:02:00Z",
                    "text": "Replace retry policy: use five attempts with exponential backoff.",
                },
            ]
            with patch.dict(
                os.environ,
                {
                    "RECALLPACK_SQLITE_PATH": str(db_path),
                    "RECALLPACK_ARTIFACT_ROOT": str(artifact_root),
                },
            ):
                observe_responses = [
                    handle_demo_request(
                        "POST",
                        "/observe",
                        json.dumps(event).encode("utf-8"),
                        ROOT,
                    )
                    for event in events
                ]
                compile_response = handle_demo_request(
                    "POST",
                    "/compile",
                    json.dumps(
                        {
                            "project_id": project_id,
                            "goal": "Update retry behavior to the current project policy.",
                            "component": "retry",
                            "budget_tokens": 512,
                        }
                    ).encode("utf-8"),
                    ROOT,
                )

            observe_payloads = [
                json.loads(response.body.decode("utf-8"))
                for response in observe_responses
            ]
            compile_payload = json.loads(compile_response.body.decode("utf-8"))
            packed_text = "\n".join(
                memory["text"] for memory in compile_payload.get("pack", {}).get("memories", [])
            )

            self.assertEqual([response.status_code for response in observe_responses], [200, 200, 200])
            self.assertEqual(
                [payload["final_result"]["operation"] for payload in observe_payloads],
                ["write", "write", "write"],
            )
            self.assertEqual(len(observe_payloads[2]["final_result"]["superseded_memory_ids"]), 1)
            self.assertEqual(compile_response.status_code, 200)
            self.assertTrue(compile_payload["compile_id"].startswith("cmp_"))
            self.assertIn("five attempts with exponential backoff", packed_text.lower())
            self.assertIn("do not add new dependencies", packed_text.lower())
            self.assertNotIn("three attempts with a fixed", packed_text.lower())
            self.assertLessEqual(compile_payload["exact_token_count"], 512)
            self.assertEqual(
                compile_payload["tokenizer"],
                {
                    "encoding": "o200k_base",
                    "package": "tiktoken",
                    "package_version": "0.13.0",
                    "exact": True,
                },
            )
            self.assertEqual(
                [compile_payload["artifacts"][key]["name"] for key in (
                    "recallpack_json",
                    "pack_md",
                    "trace_json",
                )],
                ["recallpack.json", "PACK.md", "trace.json"],
            )
            self.assertNotIn(str(Path(tmp).resolve()), json.dumps(compile_payload))
            final_directory = artifact_root / "compiles" / compile_payload["compile_id"]
            self.assertEqual(sorted(path.name for path in final_directory.iterdir()), [
                "PACK.md",
                "recallpack.json",
                "trace.json",
            ])
            published_bundle = {
                "schema_version": "4.0",
                "semantic_rules_version": "compile-semantic-rules/4.0",
                "compile_id": compile_payload["compile_id"],
                "pack": json.loads(
                    (final_directory / "recallpack.json").read_text(encoding="utf-8")
                ),
                "pack_markdown": (final_directory / "PACK.md").read_text(
                    encoding="utf-8"
                ),
                "trace": json.loads(
                    (final_directory / "trace.json").read_text(encoding="utf-8")
                ),
                "files": [
                    compile_payload["artifacts"]["recallpack_json"],
                    compile_payload["artifacts"]["pack_md"],
                    compile_payload["artifacts"]["trace_json"],
                ],
            }
            validate_compile_bundle_v4(published_bundle)

    def test_post_compile_rejects_invalid_budget_token_type(self):
        body = json.dumps(
            {
                "project_id": "project-a",
                "goal": "Update retry behavior.",
                "component": "retry",
                "budget_tokens": "many",
            }
        ).encode("utf-8")
        response = handle_demo_request("POST", "/compile", body, ROOT)
        payload = json.loads(response.body.decode("utf-8"))

        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            payload,
            {"status_code": 400, "error": "invalid_budget"},
        )

    def test_compile_rejects_non_utf8_json_with_exact_contract_error(self):
        response = handle_demo_request("POST", "/compile", b"\xff", ROOT)
        payload = json.loads(response.body)

        self.assertEqual(response.status_code, 400)
        self.assertEqual(payload, {"status_code": 400, "error": "invalid_json"})
        self.assertEqual(
            contract_errors("compile.openapi.yaml", "BadRequestResponse", payload),
            [],
        )

    def test_post_observe_writes_memory_through_http_runtime(self):
        body = json.dumps(
            {
                "project_id": "project-a",
                "session_id": "session-a",
                "event_id": "turn-001",
                "sequence_no": 1,
                "actor": "user",
                "kind": "message",
                "observed_at": "2026-06-24T00:00:00Z",
                "text": "Use three attempts with a fixed 100 ms delay in the retry helper.",
            }
        ).encode("utf-8")
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "observe.sqlite3"
            with patch.dict(os.environ, {"RECALLPACK_SQLITE_PATH": str(db_path)}):
                response = handle_demo_request("POST", "/observe", body, ROOT)
        payload = json.loads(response.body.decode("utf-8"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(payload["status_code"], 200)
        self.assertEqual(payload["final_result"]["operation"], "write")
        self.assertEqual(payload["final_result"]["memory"]["type"], "decision")
        self.assertEqual(payload["final_result"]["memory"]["component"], "retry")
        self.assertTrue(payload["final_result"]["memory"]["id"].startswith("mem_"))
        self.assertEqual(payload["state"], "completed")
        self.assertFalse(payload["replayed"])
        self.assertEqual(payload["trace"]["provider_mode"], "fake")

    def test_http_success_responses_match_v4_openapi_contracts(self):
        observe_body = json.dumps(
            {
                "project_id": "contract-project",
                "session_id": "session-a",
                "event_id": "turn-001",
                "sequence_no": 1,
                "actor": "user",
                "kind": "message",
                "observed_at": "2026-07-10T08:00:00+08:00",
                "text": "Use five attempts with exponential backoff in retry.",
            }
        ).encode("utf-8")
        compile_body = json.dumps(
            {
                "project_id": "contract-project",
                "goal": "Modify retry behavior",
                "component": "retry",
                "budget_tokens": 512,
            }
        ).encode("utf-8")
        with tempfile.TemporaryDirectory() as tmp:
            environment = {
                "RECALLPACK_SQLITE_PATH": str(Path(tmp) / "contract.sqlite3"),
                "RECALLPACK_ARTIFACT_ROOT": str(Path(tmp) / "artifacts"),
            }
            with patch.dict(os.environ, environment):
                observe_response = handle_demo_request(
                    "POST", "/observe", observe_body, ROOT
                )
                compile_response = handle_demo_request(
                    "POST", "/compile", compile_body, ROOT
                )

        observe_payload = json.loads(observe_response.body)
        compile_payload = json.loads(compile_response.body)
        self.assertEqual(observe_response.status_code, 200)
        self.assertEqual(compile_response.status_code, 200)
        self.assertEqual(
            contract_errors(
                "observe.openapi.yaml",
                "ObserveCompletedResponse",
                observe_payload,
            ),
            [],
        )
        self.assertEqual(
            contract_errors(
                "compile.openapi.yaml",
                "CompileResponse",
                compile_payload,
            ),
            [],
        )

    def test_observe_canonicalizes_timezone_before_idempotency_hashing(self):
        first_payload = {
            "project_id": "timezone-project",
            "session_id": "session-a",
            "event_id": "turn-001",
            "sequence_no": 1,
            "actor": "user",
            "kind": "message",
            "observed_at": "2026-07-10T08:00:00+08:00",
            "text": "Use five attempts with exponential backoff in retry.",
        }
        replay_payload = dict(first_payload, observed_at="2026-07-10T00:00:00Z")
        with tempfile.TemporaryDirectory() as tmp:
            with patch.dict(
                os.environ,
                {"RECALLPACK_SQLITE_PATH": str(Path(tmp) / "timezone.sqlite3")},
            ):
                first = handle_demo_request(
                    "POST", "/observe", json.dumps(first_payload).encode(), ROOT
                )
                replay = handle_demo_request(
                    "POST", "/observe", json.dumps(replay_payload).encode(), ROOT
                )

        replay_body = json.loads(replay.body)
        self.assertEqual(first.status_code, 200)
        self.assertEqual(replay.status_code, 200)
        self.assertTrue(replay_body["replayed"])
        first_body = json.loads(first.body)
        self.assertEqual(replay_body["final_result"], first_body["final_result"])
        self.assertEqual(replay_body["trace"], first_body["trace"])

    def test_observe_rejects_invalid_timestamp_with_exact_contract_error(self):
        payload = {
            "project_id": "contract-project",
            "session_id": "session-a",
            "event_id": "turn-001",
            "sequence_no": 1,
            "actor": "user",
            "kind": "message",
            "observed_at": "2026-07-10 00:00:00",
            "text": "Use five attempts with exponential backoff in retry.",
        }

        response = handle_demo_request(
            "POST", "/observe", json.dumps(payload).encode(), ROOT
        )
        body = json.loads(response.body)

        self.assertEqual(response.status_code, 400)
        self.assertEqual(body, {"status_code": 400, "error": "invalid_timestamp"})
        self.assertEqual(
            contract_errors("observe.openapi.yaml", "ErrorResponse", body),
            [],
        )

    def test_observe_retryable_failure_uses_exact_openapi_error_shape(self):
        payload = {
            "project_id": "contract-project",
            "session_id": "session-a",
            "event_id": "turn-001",
            "sequence_no": 1,
            "actor": "user",
            "kind": "message",
            "observed_at": "2026-07-10T00:00:00Z",
            "text": "Use five attempts with exponential backoff in retry.",
        }
        with tempfile.TemporaryDirectory() as tmp:
            with patch.dict(
                os.environ,
                {"RECALLPACK_SQLITE_PATH": str(Path(tmp) / "retryable.sqlite3")},
            ), patch(
                "recallpack.demo_server._memory_decider",
                return_value=RetryableNetworkDecider(),
            ):
                response = handle_demo_request(
                    "POST", "/observe", json.dumps(payload).encode(), ROOT
                )
        body = json.loads(response.body)

        self.assertEqual(response.status_code, 503)
        self.assertEqual(body["error"], "provider_network_error")
        self.assertEqual(
            contract_errors("observe.openapi.yaml", "RetryableResponse", body),
            [],
        )

    def test_observe_store_initialization_busy_maps_to_frozen_503(self):
        payload = {
            "project_id": "contract-project",
            "session_id": "session-a",
            "event_id": "turn-001",
            "sequence_no": 1,
            "actor": "user",
            "kind": "message",
            "observed_at": "2026-07-10T00:00:00Z",
            "text": "Use five attempts with exponential backoff in retry.",
        }
        with tempfile.TemporaryDirectory() as tmp, patch.dict(
            os.environ,
            {"RECALLPACK_SQLITE_PATH": str(Path(tmp) / "busy.sqlite3")},
        ), patch(
            "recallpack.demo_server.SqliteEventStore",
            side_effect=sqlite3.OperationalError("database is locked"),
        ):
            response = handle_demo_request(
                "POST", "/observe", json.dumps(payload).encode(), ROOT
            )

        body = json.loads(response.body)
        self.assertEqual(response.status_code, 503)
        self.assertEqual(body["error"], "sqlite_busy")
        self.assertEqual(
            contract_errors("observe.openapi.yaml", "RetryableResponse", body),
            [],
        )

    def test_observe_pending_duplicate_uses_exact_openapi_shape_without_processing(self):
        payload = {
            "project_id": "pending-project",
            "session_id": "session-a",
            "event_id": "turn-001",
            "sequence_no": 1,
            "actor": "user",
            "kind": "message",
            "observed_at": "2026-07-10T00:00:00Z",
            "text": "Use five attempts with exponential backoff in retry.",
        }
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "pending.sqlite3"
            store = SqliteEventStore(db_path)
            first = store.claim_event(ObserveRequest(**payload), now=100)
            with patch.dict(os.environ, {"RECALLPACK_SQLITE_PATH": str(db_path)}):
                response = handle_demo_request(
                    "POST", "/observe", json.dumps(payload).encode(), ROOT
                )

            self.assertEqual(store.attempt_count("pending-project", "session-a", "turn-001"), 1)
        body = json.loads(response.body)
        self.assertEqual(first.status_code, 202)
        self.assertEqual(response.status_code, 202)
        self.assertEqual(body["state"], "pending")
        self.assertEqual(
            contract_errors("observe.openapi.yaml", "ObservePendingResponse", body),
            [],
        )

    def test_observe_idempotency_conflict_uses_exact_openapi_shape(self):
        payload = {
            "project_id": "conflict-project",
            "session_id": "session-a",
            "event_id": "turn-001",
            "sequence_no": 1,
            "actor": "user",
            "kind": "message",
            "observed_at": "2026-07-10T00:00:00Z",
            "text": "Use five attempts with exponential backoff in retry.",
        }
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "conflict.sqlite3"
            SqliteEventStore(db_path).claim_event(ObserveRequest(**payload), now=100)
            conflicting = dict(payload, text="Use three fixed-delay attempts in retry.")
            with patch.dict(os.environ, {"RECALLPACK_SQLITE_PATH": str(db_path)}):
                response = handle_demo_request(
                    "POST", "/observe", json.dumps(conflicting).encode(), ROOT
                )

        body = json.loads(response.body)
        self.assertEqual(response.status_code, 409)
        self.assertEqual(body["error"], "idempotency_conflict")
        self.assertEqual(
            contract_errors("observe.openapi.yaml", "ConflictResponse", body),
            [],
        )

    def test_retryable_poison_event_blocks_later_session_event(self):
        first_payload = {
            "project_id": "poison-project",
            "session_id": "session-a",
            "event_id": "turn-001",
            "sequence_no": 1,
            "actor": "user",
            "kind": "message",
            "observed_at": "2026-07-10T00:00:00Z",
            "text": "Use five attempts with exponential backoff in retry.",
        }
        second_payload = dict(
            first_payload,
            event_id="turn-002",
            sequence_no=2,
            text="Do not add dependencies.",
        )
        with tempfile.TemporaryDirectory() as tmp:
            environment = {
                "RECALLPACK_SQLITE_PATH": str(Path(tmp) / "poison.sqlite3")
            }
            with patch.dict(os.environ, environment), patch(
                "recallpack.demo_server._memory_decider",
                return_value=RetryableNetworkDecider(),
            ):
                first = handle_demo_request(
                    "POST", "/observe", json.dumps(first_payload).encode(), ROOT
                )
            with patch.dict(os.environ, environment):
                second = handle_demo_request(
                    "POST", "/observe", json.dumps(second_payload).encode(), ROOT
                )

        first_body = json.loads(first.body)
        second_body = json.loads(second.body)
        self.assertEqual(first.status_code, 503)
        self.assertEqual(first_body["error"], "provider_network_error")
        self.assertEqual(second.status_code, 409)
        self.assertEqual(second_body["error"], "prior_event_incomplete")
        self.assertEqual(
            contract_errors("observe.openapi.yaml", "ConflictResponse", second_body),
            [],
        )

    def test_post_observe_uses_provider_backed_memory_decision_not_event_id_mapping(self):
        body = json.dumps(
            {
                "project_id": "project-a",
                "session_id": "natural-session",
                "event_id": "natural-language-retry-policy",
                "sequence_no": 1,
                "actor": "user",
                "kind": "message",
                "observed_at": "2026-06-24T00:00:00Z",
                "text": "Use three attempts with a fixed 100 ms delay in the retry helper.",
            }
        ).encode("utf-8")
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "observe.sqlite3"
            with patch.dict(os.environ, {"RECALLPACK_SQLITE_PATH": str(db_path)}):
                response = handle_demo_request("POST", "/observe", body, ROOT)
        payload = json.loads(response.body.decode("utf-8"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(payload["final_result"]["operation"], "write")
        self.assertEqual(payload["final_result"]["memory"]["component"], "retry")
        self.assertEqual(payload["trace"]["provider_mode"], "fake")
        self.assertTrue(payload["trace"]["request_id_present"])


if __name__ == "__main__":
    unittest.main()
