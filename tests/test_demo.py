import json
import shutil
import tempfile
import unittest
from pathlib import Path

from recallpack.demo import build_demo_payload


ROOT = Path(__file__).resolve().parents[1]
PROJECT_FIXTURE = ROOT / "fixtures" / "project-a"
SECOND_PROJECT_FIXTURE = ROOT / "fixtures" / "project-b"
THIRD_PROJECT_FIXTURE = ROOT / "fixtures" / "project-c"
FOURTH_PROJECT_FIXTURE = ROOT / "fixtures" / "project-d"
FIFTH_PROJECT_FIXTURE = ROOT / "fixtures" / "project-e"
SIXTH_PROJECT_FIXTURE = ROOT / "fixtures" / "project-f-realistic"
SEVENTH_PROJECT_FIXTURE = ROOT / "fixtures" / "project-g-auth-mode"
EIGHTH_PROJECT_FIXTURE = ROOT / "fixtures" / "project-h-projectodyssey-jit"
MICRO_SUITE = ROOT / "fixtures" / "micro-suite"


class DemoPayloadTests(unittest.TestCase):
    def test_demo_payload_exposes_learn_recall_and_evaluate_views(self):
        payload = build_demo_payload(PROJECT_FIXTURE, MICRO_SUITE)

        self.assertEqual(payload["title"], "RecallPack")
        self.assertEqual(
            [view["id"] for view in payload["views"]],
            ["learn", "recall", "evaluate"],
        )
        self.assertEqual(len(payload["learn"]["timeline"]), 12)
        self.assertIn("superseded", payload["learn"]["memory_lifecycle"][0]["status"])
        self.assertIn("active", payload["learn"]["memory_lifecycle"][1]["status"])

    def test_demo_payload_wires_m6_metrics_into_recall_and_evaluate(self):
        payload = build_demo_payload(PROJECT_FIXTURE, MICRO_SUITE)

        variants = {variant["id"]: variant for variant in payload["recall"]["variants"]}
        self.assertEqual(
            [variant["id"] for variant in payload["recall"]["variants"]],
            ["raw_full_history", "embedding_top_k_rag", "recallpack"],
        )
        self.assertEqual(variants["raw_full_history"]["label"], "Raw full history")
        self.assertFalse(
            variants["raw_full_history"]["compile_trace"]["budget_comparable"]
        )
        self.assertEqual(
            variants["embedding_top_k_rag"]["compile_trace"]["selection_source"],
            "computed_embedding_top_k_raw_events",
        )
        self.assertLess(
            variants["embedding_top_k_rag"]["metrics"]["hidden_test_pass_count"],
            variants["recallpack"]["metrics"]["hidden_test_pass_count"],
        )
        self.assertEqual(
            variants["embedding_top_k_rag"]["downstream"]["summary"]["passed"],
            1,
        )
        self.assertEqual(variants["recallpack"]["downstream"]["summary"]["passed"], 3)
        self.assertIn(
            "max_attempts=3",
            variants["embedding_top_k_rag"]["downstream"]["patch_diff"],
        )
        self.assertIn("max_attempts=5", variants["recallpack"]["downstream"]["patch_diff"])
        self.assertEqual(
            variants["recallpack"]["metrics"]["stale_leakage_rate"],
            0.0,
        )
        self.assertLessEqual(payload["recall"]["pack"]["memory_segment_tokens"], 512)
        self.assertIn("embedding top-N retrieval", payload["recall"]["pipeline"])
        self.assertEqual(
            variants["recallpack"]["compile_trace"]["retrieval_mode"],
            "embedding_top_n",
        )
        self.assertEqual(
            variants["recallpack"]["compile_trace"]["embedding_top_n_count"],
            2,
        )

        micro_suite = payload["evaluate"]["micro_suite"]
        self.assertEqual(micro_suite["case_count"], 32)
        self.assertEqual(
            micro_suite["evidence_mode"],
            "behavior_contract_fixture_suite",
        )
        self.assertIn(
            "fixture-authored",
            micro_suite["truthfulness_note"],
        )
        self.assertEqual(micro_suite["raw_counts"]["tp"], 20)
        self.assertEqual(micro_suite["edge_counts"]["correct"], 10)
        self.assertEqual(micro_suite["metrics"]["edge_f1"], 1.0)
        self.assertEqual(
            micro_suite["prediction_evidence"]["prediction_source"],
            "behavioral_runtime",
        )
        self.assertFalse(micro_suite["prediction_evidence"]["used_fixture_predictions"])
        self.assertEqual(micro_suite["sections"][0], "raw_counts")
        self.assertIn("not a broad benchmark", micro_suite["positioning"])

        boundary = payload["evidence_boundary"]
        self.assertEqual(
            boundary["local_patch_generation_mode"],
            "deterministic_context_keyed_patch_provider",
        )
        self.assertEqual(
            boundary["local_baseline_retrieval_mode"],
            "keyword_scored_fake_embedding_rerank",
        )
        self.assertEqual(
            boundary["live_qwen_evidence_mode"],
            "stored_sanitized_one_run_trace",
        )
        self.assertIn("local demo makes no live Qwen calls", boundary["judge_note"])
        self.assertEqual(boundary["title"], "Evidence Boundary")
        sections = {section["id"]: section for section in boundary["sections"]}
        self.assertIn("live_qwen", sections)
        self.assertIn("local_demo", sections)
        self.assertIn("behavior_contract", sections)
        self.assertIn(
            "provider-path integration evidence",
            " ".join(sections["live_qwen"]["items"]),
        )
        self.assertIn(
            "downstream live delta is one pass and one failed rerun",
            " ".join(sections["live_qwen"]["items"]),
        )
        self.assertIn(
            "credential-free deterministic replay",
            " ".join(sections["local_demo"]["items"]),
        )
        self.assertIn(
            "eight curated lifecycle regression fixtures",
            " ".join(sections["behavior_contract"]["items"]),
        )
        self.assertIn("not a broad benchmark", " ".join(sections["behavior_contract"]["items"]))
        self.assertIn(
            "broad coding benchmark improvement",
            boundary["do_not_claim"],
        )
        self.assertIn(
            "guaranteed live Qwen downstream success",
            boundary["do_not_claim"],
        )

    def test_demo_payload_exposes_second_fixture_generalization_proof(self):
        payload = build_demo_payload(
            PROJECT_FIXTURE,
            MICRO_SUITE,
            secondary_fixture_roots=[
                SECOND_PROJECT_FIXTURE,
                THIRD_PROJECT_FIXTURE,
                FOURTH_PROJECT_FIXTURE,
                FIFTH_PROJECT_FIXTURE,
                SIXTH_PROJECT_FIXTURE,
                SEVENTH_PROJECT_FIXTURE,
                EIGHTH_PROJECT_FIXTURE,
            ],
        )

        generalization = payload["evaluate"]["generalization_fixtures"]

        self.assertEqual(generalization["fixture_count"], 8)
        self.assertEqual(
            generalization["status"],
            "curated_lifecycle_regression_fixtures",
        )
        fixtures = {fixture["project_id"]: fixture for fixture in generalization["fixtures"]}
        self.assertEqual(
            fixtures["project-a"]["component"],
            "retry",
        )
        self.assertEqual(
            fixtures["project-b"]["component"],
            "config",
        )
        self.assertEqual(fixtures["project-b"]["baseline_downstream_tests"], "1/3")
        self.assertEqual(fixtures["project-b"]["recallpack_downstream_tests"], "3/3")
        self.assertIn("session-b:turn-001", fixtures["project-b"]["baseline_selected_sources"])
        self.assertNotIn("session-b:turn-005", fixtures["project-b"]["baseline_selected_sources"])
        self.assertEqual(
            fixtures["project-b"]["recallpack_selected_sources"],
            ["session-b:turn-005", "session-b:turn-003"],
        )
        self.assertEqual(fixtures["project-c"]["baseline_downstream_tests"], "0/3")
        self.assertEqual(fixtures["project-c"]["recallpack_downstream_tests"], "3/3")
        self.assertEqual(fixtures["project-c"]["component"], "cache")
        self.assertEqual(fixtures["project-c"]["baseline_rejection_code"], "empty_patch")
        self.assertEqual(
            fixtures["project-c"]["baseline_causal_reason"],
            "patch rejected by downstream path validator: empty_patch",
        )
        self.assertEqual(fixtures["project-d"]["baseline_downstream_tests"], "0/3")
        self.assertEqual(fixtures["project-d"]["recallpack_downstream_tests"], "3/3")
        self.assertEqual(fixtures["project-d"]["component"], "serializer")
        self.assertEqual(fixtures["project-d"]["baseline_rejection_code"], "empty_patch")
        self.assertEqual(fixtures["project-e"]["baseline_downstream_tests"], "0/3")
        self.assertEqual(fixtures["project-e"]["recallpack_downstream_tests"], "3/3")
        self.assertEqual(fixtures["project-e"]["component"], "pagination")
        self.assertEqual(fixtures["project-e"]["baseline_rejection_code"], "empty_patch")
        self.assertEqual(
            fixtures["project-e"]["fixture_structure"],
            "non_isomorphic_multi_session_sparse_event_ids",
        )
        self.assertEqual(fixtures["project-f-realistic"]["baseline_downstream_tests"], "1/3")
        self.assertEqual(fixtures["project-f-realistic"]["recallpack_downstream_tests"], "3/3")
        self.assertEqual(fixtures["project-f-realistic"]["component"], "api_client")
        self.assertEqual(
            fixtures["project-f-realistic"]["fixture_structure"],
            "realistic_repo_style_multi_session_with_noise",
        )
        self.assertIn(
            "session-f-setup:turn-002",
            fixtures["project-f-realistic"]["baseline_selected_sources"],
        )
        self.assertEqual(
            fixtures["project-f-realistic"]["recallpack_selected_sources"],
            ["session-f-fix:turn-006", "session-f-setup:turn-004"],
        )
        self.assertEqual(fixtures["project-g-auth-mode"]["baseline_downstream_tests"], "1/3")
        self.assertEqual(fixtures["project-g-auth-mode"]["recallpack_downstream_tests"], "3/3")
        self.assertEqual(fixtures["project-g-auth-mode"]["component"], "provider_auth")
        self.assertEqual(
            fixtures["project-g-auth-mode"]["fixture_structure"],
            "source_backed_ai_provider_auth_header_mode",
        )
        self.assertIn(
            "session-g-alpha:turn-002",
            fixtures["project-g-auth-mode"]["baseline_selected_sources"],
        )
        self.assertEqual(
            fixtures["project-g-auth-mode"]["recallpack_selected_sources"],
            ["session-g-alpha:turn-004", "session-g-fix:turn-006"],
        )
        self.assertEqual(fixtures["project-h-projectodyssey-jit"]["baseline_downstream_tests"], "1/3")
        self.assertEqual(fixtures["project-h-projectodyssey-jit"]["recallpack_downstream_tests"], "3/3")
        self.assertEqual(fixtures["project-h-projectodyssey-jit"]["component"], "ci_policy")
        self.assertEqual(
            fixtures["project-h-projectodyssey-jit"]["fixture_structure"],
            "source_backed_projectodyssey_jit_unrigged_retrieval",
        )
        self.assertIn(
            "session-h-history:turn-002",
            fixtures["project-h-projectodyssey-jit"]["baseline_selected_sources"],
        )
        self.assertNotIn(
            "session-h-current:turn-006",
            fixtures["project-h-projectodyssey-jit"]["baseline_selected_sources"],
        )
        self.assertEqual(
            fixtures["project-h-projectodyssey-jit"]["recallpack_selected_sources"],
            ["session-h-current:turn-006", "session-h-history:turn-004"],
        )
        self.assertIn(
            "eight local fixtures",
            generalization["credibility_note"],
        )
        self.assertIn(
            "source-backed ProjectOdyssey JIT scenario",
            generalization["credibility_note"],
        )

    def test_demo_payload_exposes_qwen_load_bearing_traces_without_live_run(self):
        payload = build_demo_payload(PROJECT_FIXTURE, MICRO_SUITE)

        proof = payload["qwen_load_bearing"]
        trace_roles = [trace["provider_role"] for trace in proof["provider_traces"]]
        model_names = [trace["model_name"] for trace in proof["provider_traces"]]

        self.assertFalse(proof["live_qwen_run"])
        self.assertEqual(proof["live_status"], "gated_not_run")
        self.assertIn("memory_decision", trace_roles)
        self.assertIn("embedding", trace_roles)
        self.assertIn("rerank", trace_roles)
        self.assertIn("text-embedding-v4", model_names)
        self.assertIn("qwen3-rerank", model_names)
        self.assertIn("qwen", model_names[0])
        self.assertEqual(
            proof["deterministic_runtime_work"],
            [
                "event ordering and lease fencing",
                "schema validation and failure handling",
                "active/superseded lifecycle filtering",
                "512-token budget selection",
                "PACK.md and recallpack.json assembly",
            ],
        )
        for trace in proof["provider_traces"]:
            self.assertFalse(trace["is_live"])
            self.assertEqual(trace["deterministic_fallback_status"], "fake_provider_deterministic")
            self.assertNotIn("secret", str(trace).lower())
            self.assertNotIn("tool_arguments", str(trace))

    def test_demo_payload_can_use_explicit_live_qwen_trace(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            trace_path = Path(temp_dir) / "live-qwen-trace.json"
            trace_path.write_text(
                json.dumps(
                    {
                        "live_qwen_run": True,
                        "live_status": "live_contract_passed",
                        "provider_traces": [
                            {
                                "provider_role": "memory_decision",
                                "model_name": "qwen-plus",
                                "request_purpose": "extract_classify_and_judge_memory_lifecycle",
                                "input_item_count": 2,
                                "input_token_estimate": 40,
                                "output_item_count": 1,
                                "is_live": True,
                                "deterministic_fallback_status": "live_qwen",
                                "request_id_present": True,
                            }
                        ],
                        "actual_qwen_token_usage": {
                            "memory_decision_total_tokens": 32,
                            "embedding_total_tokens": 15,
                            "rerank_total_tokens": 13,
                        },
                        "qwen_model_work": ["memory decision"],
                        "deterministic_runtime_work": ["budget selection"],
                    }
                )
            )

            payload = build_demo_payload(
                PROJECT_FIXTURE,
                MICRO_SUITE,
                live_qwen_trace_path=trace_path,
            )

        proof = payload["qwen_load_bearing"]
        self.assertTrue(proof["live_qwen_run"])
        self.assertEqual(proof["live_status"], "live_contract_passed")
        self.assertEqual(payload["hero_story"]["live_qwen_status"], "live_contract_passed")
        self.assertEqual(
            proof["actual_qwen_token_usage"]["memory_decision_total_tokens"],
            32,
        )
        self.assertEqual(proof["provider_traces"][0]["model_name"], "qwen-plus")
        self.assertNotIn("secret", str(proof).lower())

    def test_demo_payload_declares_approved_ecs_deployment_proof(self):
        payload = build_demo_payload(PROJECT_FIXTURE, MICRO_SUITE)
        deployment = payload["deployment_proof"]

        self.assertTrue(deployment["approval_required"])
        self.assertEqual(
            deployment["target"],
            "Alibaba Cloud ECS + Docker + SQLite",
        )
        self.assertEqual(deployment["runtime_limits"]["deployment_replicas"], 1)
        self.assertEqual(deployment["runtime_limits"]["application_workers"], 1)
        self.assertEqual(
            deployment["public_deployment"]["status"],
            "approved_public_ecs_passed",
        )
        self.assertEqual(
            deployment["public_deployment"]["url"],
            "http://101.133.224.223/",
        )
        self.assertEqual(
            deployment["public_deployment"]["judge_smoke_status"],
            "passed",
        )
        self.assertEqual(
            deployment["public_deployment"]["port_mapping"],
            "0.0.0.0:80->8789/tcp",
        )
        self.assertEqual(
            deployment["public_deployment"]["image"],
            "recallpack-demo:cloud",
        )
        self.assertEqual(
            deployment["public_deployment"]["source_bundle"],
            "latest sanitized bundle",
        )
        self.assertEqual(
            deployment["public_deployment"]["redeployed_at"],
            "2026-07-04",
        )
        self.assertEqual(
            deployment["public_deployment"]["runtime"],
            "ThreadingHTTPServer",
        )
        self.assertNotIn(
            "no public endpoint is exposed without explicit approval",
            deployment["non_actions"],
        )

    def test_demo_payload_exposes_first_screen_hero_story(self):
        payload = build_demo_payload(PROJECT_FIXTURE, MICRO_SUITE)

        story = payload["hero_story"]

        self.assertEqual(
            story["headline"],
            "RecallPack makes stale-decision exclusion structural",
        )
        self.assertIn("superseded decision", story["failure_summary"])
        self.assertIn("filters superseded memory before rerank", story["failure_summary"])
        self.assertEqual(
            story["baseline"]["test_summary"],
            {"passed": 1, "failed": 2, "total": 3},
        )
        self.assertEqual(
            story["baseline"]["label"],
            "Embedding top-N + rerank stale baseline",
        )
        self.assertEqual(
            story["recallpack"]["test_summary"],
            {"passed": 3, "failed": 0, "total": 3},
        )
        self.assertEqual(
            story["retrieval_path"],
            ["embedding top-N", "qwen3-rerank", "512-token budget selector"],
        )
        self.assertEqual(story["live_qwen_status"], "gated_not_run")
        self.assertFalse(story["live_qwen_run"])
        self.assertEqual(
            story["patch_generation"]["provider_role"],
            "patch_generation",
        )
        self.assertEqual(
            story["patch_generation"]["local_mode"],
            "deterministic_context_keyed_patch_provider",
        )
        self.assertEqual(
            story["patch_generation"]["live_mode"],
            "stored_qwen_e2e_trace_only",
        )
        self.assertIn(
            "local deterministic context-keyed patch provider",
            story["patch_generation"]["truthfulness_note"],
        )
        self.assertTrue(story["patch_generation"]["same_provider_contract"])
        self.assertFalse(story["patch_generation"]["used_gold_patch_variants"])
        self.assertEqual(
            story["patch_generation"]["baseline_model_name"],
            story["patch_generation"]["recallpack_model_name"],
        )
        self.assertIn("max_attempts=3", story["baseline"]["patch_signal"])
        self.assertIn("max_attempts=5", story["recallpack"]["patch_signal"])
        self.assertEqual(
            story["memory_lifecycle_summary"]["superseded"],
            ["mem_retry_old"],
        )
        self.assertEqual(
            story["memory_lifecycle_summary"]["active"],
            ["mem_retry_current", "mem_dependency_policy"],
        )

    def test_demo_payload_exposes_first_run_handoff_simulator(self):
        payload = build_demo_payload(PROJECT_FIXTURE, MICRO_SUITE)

        simulator = payload["handoff_simulator"]

        self.assertEqual(simulator["title"], "First-Run Handoff Simulator")
        self.assertEqual(
            simulator["task"],
            "Update the retry helper to the current project policy.",
        )
        self.assertEqual(
            [step["id"] for step in simulator["flow"]],
            [
                "incoming_task",
                "raw_history_baseline",
                "recallpack_compile",
                "downstream_hidden_tests",
            ],
        )
        self.assertEqual(
            simulator["baseline"]["context_mode"],
            "computed_embedding_top_k_raw_events",
        )
        self.assertIn(
            "session-a:turn-001",
            simulator["baseline"]["selected_sources"],
        )
        self.assertEqual(simulator["baseline"]["hidden_tests"], "1/3")
        self.assertIn("max_attempts=3", simulator["baseline"]["patch_signal"])
        self.assertEqual(
            simulator["recallpack"]["context_mode"],
            "active_memory_lifecycle_pack",
        )
        self.assertEqual(
            simulator["recallpack"]["selected_sources"],
            ["session-a:turn-005", "session-a:turn-003"],
        )
        self.assertNotIn(
            "session-a:turn-001",
            simulator["recallpack"]["selected_sources"],
        )
        self.assertEqual(simulator["recallpack"]["hidden_tests"], "3/3")
        self.assertIn("max_attempts=5", simulator["recallpack"]["patch_signal"])
        self.assertEqual(
            simulator["why_it_wins"],
            [
                "local replay baseline retrieves stale raw history and writes the old retry policy",
                "RecallPack supersedes stale memory before compile",
                "RecallPack keeps the active retry decision plus dependency preference inside the 512-token pack",
                "both patches are executed in a temp repo against the same fixture tests",
            ],
        )
        self.assertEqual(
            simulator["qwen_boundary"]["live_status"],
            "gated_not_run",
        )
        self.assertEqual(
            simulator["qwen_boundary"]["standalone_contract_status"],
            "gated_not_run",
        )
        self.assertEqual(
            simulator["qwen_boundary"]["live_observe_compile_e2e_status"],
            "not_claimed",
        )
        self.assertEqual(
            simulator["qwen_boundary"]["first_screen_lines"],
            [
                "Standalone Qwen API smoke: not run",
                "Stored live provider-path E2E: not claimed",
                "Lifecycle filtering: not claimed",
            ],
        )
        self.assertIn(
            "text-embedding-v4",
            " ".join(simulator["qwen_boundary"]["model_work"]),
        )

    def test_demo_payload_exposes_one_click_handoff_replay(self):
        payload = build_demo_payload(PROJECT_FIXTURE, MICRO_SUITE)

        replay = payload["handoff_replay"]

        self.assertEqual(replay["title"], "Deterministic Stale-Memory Failure Replay")
        self.assertEqual(replay["status"], "local_fixture_evidence")
        self.assertEqual(replay["mode_label"], "Deterministic scripted replay")
        self.assertIn("authored deterministic replay", replay["structural_claim"].lower())
        self.assertIn("lifecycle filter", replay["structural_claim"])
        self.assertEqual(
            replay["local_patch_generation_mode"],
            "deterministic_context_keyed_patch_provider",
        )
        self.assertIn("not live Qwen inference", replay["truthfulness_note"])
        self.assertEqual(replay["default_step_id"], "stale_context")
        self.assertEqual(replay["play_label"], "Replay handoff")
        self.assertEqual(
            replay["evidence_mode"],
            "existing downstream temp-repo patch and fixture-test execution",
        )
        self.assertEqual(
            [step["id"] for step in replay["steps"]],
            [
                "stale_context",
                "wrong_patch",
                "active_memory_pack",
                "passing_patch",
            ],
        )

        steps = {step["id"]: step for step in replay["steps"]}
        self.assertEqual(steps["stale_context"]["variant_id"], "embedding_top_k_rag")
        self.assertEqual(steps["stale_context"]["hidden_tests"], "1/3")
        self.assertIn("session-a:turn-001", steps["stale_context"]["selected_sources"])
        self.assertIn("session-a:turn-008", steps["stale_context"]["selected_sources"])
        self.assertIn("superseded", steps["stale_context"]["memory_status"])
        self.assertEqual(steps["wrong_patch"]["result"], "wrong_retry_patch")
        self.assertEqual(steps["wrong_patch"]["hidden_tests"], "1/3")
        self.assertIn("max_attempts=3", steps["wrong_patch"]["patch_signal"])
        self.assertIn("temp repo", steps["wrong_patch"]["evidence"])

        self.assertEqual(steps["active_memory_pack"]["variant_id"], "recallpack")
        self.assertEqual(steps["active_memory_pack"]["hidden_tests"], "3/3")
        self.assertEqual(
            steps["active_memory_pack"]["selected_sources"],
            ["session-a:turn-005", "session-a:turn-003"],
        )
        self.assertNotIn(
            "session-a:turn-001",
            steps["active_memory_pack"]["selected_sources"],
        )
        self.assertIn("active", steps["active_memory_pack"]["memory_status"])
        self.assertEqual(steps["passing_patch"]["result"], "correct_retry_patch")
        self.assertEqual(steps["passing_patch"]["hidden_tests"], "3/3")
        self.assertIn("max_attempts=5", steps["passing_patch"]["patch_signal"])
        self.assertFalse(replay["claims_live_qwen_e2e"])

    def test_demo_payload_distinguishes_standalone_qwen_contract_from_live_e2e(self):
        live_trace = ROOT / "docs" / "submission" / "live-qwen-trace.json"
        live_e2e_trace = ROOT / "docs" / "submission" / "live-qwen-e2e-trace.json"
        fresh_m98_trace = ROOT / "docs" / "submission" / "live-qwen-m98-rerun-trace.json"
        projectodyssey_trace = (
            ROOT / "docs" / "submission" / "projectodyssey-live-qwen-e2e-trace.json"
        )

        payload = build_demo_payload(
            PROJECT_FIXTURE,
            MICRO_SUITE,
            live_qwen_trace_path=live_trace,
            live_qwen_e2e_trace_path=live_e2e_trace,
            fresh_m98_live_rerun_trace_path=fresh_m98_trace,
            projectodyssey_live_qwen_e2e_trace_path=projectodyssey_trace,
        )

        proof = payload["qwen_load_bearing"]
        simulator = payload["handoff_simulator"]

        self.assertEqual(proof["live_status"], "live_contract_passed")
        self.assertEqual(proof["standalone_contract_status"], "live_contract_passed")
        self.assertEqual(proof["live_qwen_e2e_status"], "live_e2e_passed")
        self.assertEqual(proof["stored_live_qwen_e2e_status"], "live_e2e_passed")
        self.assertEqual(proof["fresh_m98_live_rerun_status"], "live_e2e_failed")
        self.assertEqual(
            proof["fresh_m98_live_rerun_source"],
            "docs/submission/live-qwen-m98-rerun-trace.json",
        )
        self.assertIn("2/3", proof["fresh_m98_live_rerun_summary"])
        self.assertEqual(
            proof["projectodyssey_live_e2e_status"],
            "live_e2e_passed",
        )
        self.assertEqual(
            proof["projectodyssey_live_e2e_source"],
            "docs/submission/projectodyssey-live-qwen-e2e-trace.json",
        )
        self.assertIn("RecallPack 3/3", proof["projectodyssey_live_e2e_summary"])
        self.assertEqual(
            simulator["qwen_boundary"]["first_screen_lines"],
            [
                "Standalone Qwen API smoke: passed",
                "Stored live provider-path E2E: one pass; fresh rerun failed",
                "ProjectOdyssey live E2E: passed",
                "Lifecycle filtering: held in stored live runs",
            ],
        )
        self.assertNotIn(
            "live Qwen E2E live_contract_passed",
            " ".join(simulator["qwen_boundary"]["first_screen_lines"]),
        )

    def test_demo_payload_exposes_live_qwen_trace_explorer_without_raw_payloads(self):
        live_trace = ROOT / "docs" / "submission" / "live-qwen-trace.json"
        live_e2e_trace = ROOT / "docs" / "submission" / "live-qwen-e2e-trace.json"
        fresh_m98_trace = ROOT / "docs" / "submission" / "live-qwen-m98-rerun-trace.json"

        payload = build_demo_payload(
            PROJECT_FIXTURE,
            MICRO_SUITE,
            live_qwen_trace_path=live_trace,
            live_qwen_e2e_trace_path=live_e2e_trace,
            fresh_m98_live_rerun_trace_path=fresh_m98_trace,
        )

        explorer = payload["qwen_load_bearing"]["trace_explorer"]

        self.assertEqual(explorer["status"], "live_e2e_passed")
        self.assertEqual(explorer["source"], "docs/submission/live-qwen-e2e-trace.json")
        self.assertEqual(explorer["source_kind"], "checked_in_sanitized_trace")
        self.assertEqual(explorer["display_title"], "Stored Live Qwen Trace")
        self.assertEqual(explorer["observed_event_count"], 12)
        self.assertEqual(explorer["selected_sources"][0], "session-a:turn-005")
        self.assertIn("session-a:turn-001", explorer["excluded_sources_checked"])
        self.assertTrue(explorer["safety_boundary"]["sanitized_trace_only"])
        self.assertTrue(explorer["safety_boundary"]["no_credentials"])
        self.assertTrue(explorer["safety_boundary"]["prompts_redacted"])
        self.assertTrue(explorer["safety_boundary"]["local_demo_no_live_calls"])
        self.assertTrue(explorer["safety_boundary"]["stored_trace_no_live_call"])

        roles = {role["provider_role"]: role for role in explorer["role_summary"]}
        self.assertEqual(roles["memory_decision"]["trace_count"], 12)
        self.assertEqual(roles["embedding"]["model_name"], "text-embedding-v4")
        self.assertEqual(roles["rerank"]["model_name"], "qwen3-rerank")
        self.assertEqual(roles["patch_generation"]["trace_count"], 2)
        self.assertEqual(
            roles["patch_generation"]["token_usage_key"],
            "patch_generation_total_tokens",
        )

        stage_ids = [stage["id"] for stage in explorer["stages"]]
        self.assertEqual(
            stage_ids,
            [
                "observe_memory_decisions",
                "compile_embedding_retrieval",
                "compile_rerank",
                "downstream_patch_generation",
            ],
        )
        self.assertIn("baseline 1/3", explorer["downstream_summary"])
        self.assertIn("RecallPack 3/3", explorer["downstream_summary"])
        downstream_stage = {
            stage["id"]: stage for stage in explorer["stages"]
        }["downstream_patch_generation"]
        self.assertIn("stored live E2E", downstream_stage["mode_note"])
        self.assertIn("local demo", downstream_stage["mode_note"])
        self.assertNotIn("api_key", str(explorer).lower())
        self.assertNotIn("tool_arguments", str(explorer))
        self.assertNotIn("raw_prompt", str(explorer))

    def test_explicit_e2e_trace_override_is_not_misattributed_or_path_leaked(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            trace_path = Path(temp_dir) / "custom-e2e.json"
            trace_path.write_text(
                json.dumps(
                    {
                        "live_status": "live_e2e_passed",
                        "provider_traces": [],
                        "selected_sources": ["custom:turn-001"],
                    }
                )
            )

            payload = build_demo_payload(
                PROJECT_FIXTURE,
                MICRO_SUITE,
                live_qwen_e2e_trace_path=trace_path,
            )

        explorer = payload["qwen_load_bearing"]["trace_explorer"]
        self.assertEqual(
            explorer["source"],
            "explicit_live_qwen_e2e_trace_override",
        )
        self.assertEqual(
            explorer["source_kind"],
            "explicit_trace_override_unverified_provenance",
        )
        self.assertEqual(explorer["display_title"], "Explicit E2E Trace Override")
        self.assertFalse(explorer["safety_boundary"]["sanitized_trace_only"])
        self.assertFalse(explorer["safety_boundary"]["provenance_verified"])
        self.assertNotIn(temp_dir, str(explorer))
        self.assertNotIn("docs/submission/live-qwen-e2e-trace.json", str(explorer))

    def test_sanitized_bundle_trace_is_checked_in_to_its_own_project_surface(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            bundle_root = Path(temp_dir) / "bundle"
            fixture_root = bundle_root / "fixtures" / "project-a"
            micro_suite_root = bundle_root / "fixtures" / "micro-suite"
            trace_path = (
                bundle_root
                / "docs"
                / "submission"
                / "live-qwen-e2e-trace.json"
            )
            shutil.copytree(PROJECT_FIXTURE, fixture_root)
            shutil.copytree(MICRO_SUITE, micro_suite_root)
            trace_path.parent.mkdir(parents=True)
            shutil.copy2(
                ROOT / "docs" / "submission" / "live-qwen-e2e-trace.json",
                trace_path,
            )

            payload = build_demo_payload(
                fixture_root,
                micro_suite_root,
                live_qwen_e2e_trace_path=trace_path,
            )

        explorer = payload["qwen_load_bearing"]["trace_explorer"]
        self.assertEqual(
            explorer["source"],
            "docs/submission/live-qwen-e2e-trace.json",
        )
        self.assertEqual(explorer["source_kind"], "checked_in_sanitized_trace")
        self.assertTrue(explorer["safety_boundary"]["provenance_verified"])

    def test_e2e_trace_symlink_override_is_not_promoted_to_checked_in(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            alias_path = Path(temp_dir) / "trace-alias.json"
            alias_path.symlink_to(
                ROOT / "docs" / "submission" / "live-qwen-e2e-trace.json"
            )

            payload = build_demo_payload(
                PROJECT_FIXTURE,
                MICRO_SUITE,
                live_qwen_e2e_trace_path=alias_path,
            )

        explorer = payload["qwen_load_bearing"]["trace_explorer"]
        self.assertEqual(
            explorer["source_kind"],
            "explicit_trace_override_unverified_provenance",
        )
        self.assertFalse(explorer["safety_boundary"]["provenance_verified"])

    def test_demo_payload_exposes_judge_first_screen_summary(self):
        payload = build_demo_payload(PROJECT_FIXTURE, MICRO_SUITE)

        summary = payload["judge_first_screen"]

        self.assertEqual(
            summary["positioning"],
            "MemoryAgent stale-aware lifecycle proof for coding-agent handoffs",
        )
        self.assertEqual(
            [item["id"] for item in summary["comparison"]],
            ["raw_full_history", "embedding_top_k_rag", "recallpack"],
        )
        self.assertEqual(summary["comparison"][0]["role"], "reference_not_budget_comparable")
        self.assertEqual(summary["comparison"][1]["role"], "computed_budget_baseline")
        self.assertEqual(
            summary["comparison"][1]["label"],
            "Keyword fake-embedding + rerank RAG",
        )
        self.assertEqual(summary["comparison"][1]["downstream_tests"], "1/3")
        self.assertEqual(summary["comparison"][2]["downstream_tests"], "3/3")
        self.assertEqual(
            summary["comparison"][1]["selection_source"],
            "computed_embedding_top_k_raw_events",
        )
        self.assertIn("not source-picked", summary["comparison"][1]["fairness_note"])
        self.assertIn(
            "temp repo fixture tests",
            summary["downstream_proof"],
        )
        self.assertIn(
            "deterministic context-keyed patch provider",
            summary["downstream_proof"],
        )
        self.assertIn("memory extraction", summary["qwen_load_bearing"]["model_work"][0])
        self.assertIn(
            "budget selection",
            " ".join(summary["qwen_load_bearing"]["deterministic_runtime_work"]),
        )
        self.assertEqual(summary["qwen_load_bearing"]["live_status"], "gated_not_run")
        self.assertIn("no credentials", summary["qwen_load_bearing"]["local_mode"])


if __name__ == "__main__":
    unittest.main()
