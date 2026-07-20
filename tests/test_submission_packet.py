import unittest
import tempfile
from pathlib import Path

from recallpack.submission_packet import build_review_packet


ROOT = Path(__file__).resolve().parents[1]


class SubmissionPacketTests(unittest.TestCase):
    def test_review_packet_contains_positioning_metrics_and_safety_gates(self):
        packet = build_review_packet(ROOT)

        self.assertEqual(
            packet,
            (ROOT / "docs" / "submission" / "review-packet.md").read_text(),
        )

        self.assertIn("# RecallPack Review Packet", packet)
        self.assertIn("MemoryAgent", packet)
        self.assertIn("cross-session memory lifecycle", packet)
        self.assertIn("stale-aware", packet)
        self.assertIn("text-embedding-v4", packet)
        self.assertIn("qwen3-rerank", packet)
        self.assertIn("Qwen text model", packet)
        self.assertIn("OpenAI-compatible tools/tool_choice", packet)
        self.assertIn("qwen3.7-plus-2026-05-26", packet)
        self.assertIn(
            "current live E2E trace is the primary current-model evidence",
            packet,
        )
        self.assertIn(
            "legacy standalone live smoke is preserved only as a historical contract smoke",
            packet,
        )
        self.assertIn("M43 adds a gated live Qwen E2E observe/compile runner", packet)
        self.assertIn("M47 hardens the memory-decision contract", packet)
        self.assertIn("M64 extends the credential-free live E2E preflight", packet)
        self.assertIn(
            "M65 stores one sanitized live Qwen provider-path integration",
            packet,
        )
        self.assertIn("M75 reconciles current shipped Qwen model evidence", packet)
        self.assertIn("M76 adds a real text-embedding-v4 raw-history baseline preflight", packet)
        self.assertIn("latest local package", packet)
        self.assertIn("M98 evidence snapshot", packet)
        self.assertIn("M86 recording release-candidate sync", packet)
        self.assertIn("M99 current-package wording sync", packet)
        self.assertIn("M92/M99 submission media copy consistency gate", packet)
        self.assertIn("built-but-not-uploaded presentation PPT", packet)
        self.assertIn("M93 judge first-run command contract", packet)
        self.assertIn("M94 public release gate command contract", packet)
        self.assertIn("M106 current-day release readiness refresh", packet)
        self.assertIn("M96 current-package wording guardrail", packet)
        self.assertIn("M97 source-to-bundle parity preflight", packet)
        self.assertNotIn("current M85 local release candidate", packet)
        self.assertIn("M98 responds to adversarial review", packet)
        self.assertIn(
            "The stored `live_e2e_passed` trace demonstrates provider-path integration",
            packet,
        )
        self.assertIn(
            "downstream live reproducibility remains an open empirical question",
            packet,
        )
        self.assertNotIn("current M81 local release candidate", packet)
        self.assertIn("M45 adds a first-run handoff simulator", packet)
        self.assertIn("live Qwen provider-path integration trace: live_e2e_passed", packet)
        self.assertIn(
            "selected_sources=['session-a:turn-005', 'session-a:turn-004', 'session-a:turn-003']",
            packet,
        )
        self.assertIn("live Qwen E2E one-run integration outcome", packet)
        self.assertIn("turn-004` is supporting retry-failure evidence", packet)
        self.assertIn(
            "live Qwen E2E one-run downstream result, not a headline metric: baseline 1/3; RecallPack 3/3",
            packet,
        )
        self.assertIn(
            "live raw-history embedding+rerank baseline traces: 2 stored runs; active retry selected in 2/2; stale retry selected in 0/2",
            packet,
        )
        self.assertIn("not live frequency evidence", packet)
        self.assertIn("structured event metadata", packet)
        self.assertIn("descriptive tool schema", packet)
        self.assertIn("preflight_status: ready_for_live_e2e_rerun", packet)
        self.assertIn("network_calls_made=false", packet)
        self.assertIn("request_role_counts: memory_decision=12 embedding=16 rerank=2 patch_generation=2", packet)
        self.assertIn("ProjectOdyssey live Qwen E2E preflight", packet)
        self.assertIn(
            "ProjectOdyssey preflight expected selected sources: ['session-h-current:turn-006', 'session-h-history:turn-004']; future live reruns remain gated.",
            packet,
        )
        self.assertIn("ProjectOdyssey live Qwen E2E run: live_e2e_passed", packet)
        self.assertIn(
            "ProjectOdyssey live selected_sources=['session-h-current:turn-006', 'session-h-history:turn-004']",
            packet,
        )
        self.assertIn("required_sources_selected=True", packet)
        self.assertIn("stale_sources_excluded=True", packet)
        self.assertIn(
            "ProjectOdyssey live downstream result: baseline 1/3; RecallPack 3/3",
            packet,
        )
        self.assertIn(
            "RecallPack live-generated patch passed 3/3 downstream fixture tests",
            packet,
        )
        self.assertIn("Qwen provider trace evidence", packet)
        self.assertIn(
            "standalone live API smoke passed: yes, sanitized contract trace recorded",
            packet,
        )
        self.assertIn("Raw full-history reference selected 12 events", packet)
        self.assertIn("not budget-comparable", packet)
        self.assertIn(
            "Keyword-scored fake-embedding + rerank raw-history baseline is computed from raw event text",
            packet,
        )
        self.assertIn("not from fixture-selected source IDs", packet)
        self.assertIn(
            "First-screen story: keyword-scored fake-embedding + rerank raw-history handoff fails 1/3",
            packet,
        )
        self.assertIn("RecallPack active memory handoff passes 3/3", packet)
        self.assertIn("First-run handoff simulator: baseline 1/3, RecallPack 3/3", packet)
        self.assertIn(
            "first-screen retrieval path: embedding top-N -> qwen3-rerank -> estimated 512-token serialized-memory budget selector",
            packet,
        )
        self.assertIn(
            "recorded Qwen trace status: standalone live API smoke passed (stored status value: live_contract_passed)",
            packet,
        )
        self.assertIn("Quality hardening audit", packet)
        self.assertIn("Skeptical judge Q&A", packet)
        self.assertIn("docs/submission/skeptical-judge-qa.md", packet)
        self.assertIn("claim-to-evidence", packet)
        self.assertIn("Eight curated lifecycle fixtures", packet)
        self.assertIn("project-b config", packet)
        self.assertIn("project-c cache", packet)
        self.assertIn("project-d serializer", packet)
        self.assertIn("project-e pagination", packet)
        self.assertIn("project-f-realistic api_client", packet)
        self.assertIn("project-g-auth-mode provider_auth", packet)
        self.assertIn("project-h-projectodyssey-jit ci_policy", packet)
        self.assertIn("project-b config: baseline 1/3, RecallPack 3/3", packet)
        self.assertIn("project-c cache: baseline 0/3, RecallPack 3/3", packet)
        self.assertIn("project-d serializer: baseline 0/3, RecallPack 3/3", packet)
        self.assertIn("project-e pagination: baseline 0/3, RecallPack 3/3", packet)
        self.assertIn("project-c cache: baseline rejection=empty_patch", packet)
        self.assertIn("project-d serializer: baseline rejection=empty_patch", packet)
        self.assertIn("project-e pagination: baseline rejection=empty_patch", packet)
        self.assertIn(
            "project-f-realistic api_client: baseline 1/3, RecallPack 3/3",
            packet,
        )
        self.assertIn(
            "project-g-auth-mode provider_auth: baseline 1/3, RecallPack 3/3",
            packet,
        )
        self.assertIn(
            "project-h-projectodyssey-jit ci_policy: baseline 1/3, RecallPack 3/3",
            packet,
        )
        self.assertIn("ProjectOdyssey JIT scenario", packet)
        self.assertIn("unrigged keyword-provider baseline", packet)
        self.assertIn("not a broad benchmark", packet)
        banned_two_way_claim = "Recall view compares raw-history RAG with " + "RecallPack."
        self.assertNotIn(banned_two_way_claim, packet)
        self.assertIn("memory_decision -> qwen", packet)
        self.assertIn("embedding -> text-embedding-v4", packet)
        self.assertIn("rerank -> qwen3-rerank", packet)
        self.assertIn(
            "live Qwen E2E current-model trace: qwen3.7-plus-2026-05-26",
            packet,
        )
        self.assertIn(
            "real embedding baseline preflight: ready_for_live_embedding_baseline_rerun",
            packet,
        )
        self.assertIn(
            "real embedding baseline expected selected_sources=['session-a:turn-001', 'session-a:turn-003']",
            packet,
        )
        self.assertIn(
            "/compile local retrieval: deterministic keyword fake embedding top-N + qwen3-rerank-shaped fake rerank",
            packet,
        )
        self.assertIn(
            "/compile local HTTP path uses deterministic keyword fake embedding/rerank",
            packet,
        )
        self.assertIn("not zero-vector or identity-rerank smoke", packet)
        self.assertIn("Learn view includes the first-run handoff simulator", packet)
        self.assertIn("local fake-embedding top-N candidates are passed into fake rerank before budget selection", packet)
        self.assertIn("32-event behavior contract fixture suite", packet)
        self.assertIn("behavior contract fixture suite", packet)
        self.assertIn("fixture prediction fields are ignored", packet)
        self.assertIn("baseline downstream fixture tests: 1/3", packet)
        self.assertIn("baseline source-recall score: 0/3", packet)
        self.assertIn("RecallPack downstream fixture tests: 3/3", packet)
        self.assertIn("deterministic context-keyed patch provider", packet)
        self.assertIn("does not read gold patch_variants", packet)
        self.assertIn("same deterministic context-keyed local patch provider", packet)
        self.assertIn("executing fixture tests against a temp repo", packet)
        self.assertIn("wrong retry patch", packet)
        self.assertIn(
            "behavior-contract runtime counts, not model-quality metrics: TP=20 FP=0 FN=0 TN=12",
            packet,
        )
        self.assertIn(
            "behavior-contract supersession edges, oracle-backed runtime check: 10/10 correct",
            packet,
        )
        self.assertIn("POST /compile", packet)
        self.assertIn("POST /observe", packet)
        self.assertIn("POST /observe is exposed by the demo backend", packet)
        self.assertIn("GET /api/health exposes compact readiness", packet)
        self.assertIn("Judge smoke verifies GET /, GET /api/demo first-screen story", packet)
        self.assertIn("Qwen provider roles, POST /observe, and POST /compile", packet)
        self.assertIn("M73 live Qwen trace explorer", packet)
        self.assertIn("role_summary", packet)
        self.assertIn("sanitized trace only", packet)
        self.assertIn("local demo makes no live Qwen calls", packet)
        self.assertIn("M74 external-review remediation", packet)
        self.assertIn("Stored Live Qwen Trace", packet)
        self.assertIn("local deterministic context-keyed patch provider", packet)
        self.assertIn("keyword-scored fake-embedding baseline", packet)
        self.assertIn("behavior contract fixture suite", packet)
        self.assertIn("## Evidence Boundary", packet)
        self.assertIn("provider-path integration evidence", packet)
        self.assertIn("downstream live delta is one pass and one failed rerun", packet)
        self.assertIn("eight curated lifecycle regression fixtures", packet)
        self.assertIn("What we do not claim", packet)
        self.assertIn("broad coding benchmark improvement", packet)
        self.assertIn("guaranteed live Qwen downstream success", packet)
        self.assertIn("M72 current screenshot gallery", packet)
        self.assertIn("docs/submission/media/m71-replay", packet)
        self.assertIn("01-one-click-stale-memory-replay.png", packet)
        self.assertIn("sanitized local submission bundle", packet)
        self.assertIn("SUBMISSION_MANIFEST.md includes judge quick checks", packet)
        self.assertIn("Latest Docker proof: M104 image from the prior verified sanitized bundle", packet)
        self.assertIn("recallpack-demo:cloud", packet)
        self.assertIn(
            "Current public ECS deployment: M104 credential-free runtime from the prior verified 7/4 sanitized bundle.",
            packet,
        )
        self.assertIn("timestamped M104 local image and recallpack-demo:cloud", packet)
        self.assertIn(
            "Public ECS judge smoke passed after the M104 redeploy",
            packet,
        )
        self.assertIn("Fresh-clone rehearsal: passed", packet)
        self.assertIn("Fresh-clone public surface gate checks required public files", packet)
        self.assertIn("manifest judge quick checks before running server smoke", packet)
        self.assertIn("Static demo parity gate compares web/demo-data.js", packet)
        self.assertIn("current fixture-backed demo payload", packet)
        self.assertIn("PYTHONPATH=src python3 tools/fresh_clone_smoke.py --source .", packet)
        self.assertIn("Full fresh-clone rehearsal: available with --full", packet)
        self.assertIn("tools/fresh_clone_smoke.py", packet)
        self.assertIn("approved Alibaba Cloud ECS deployment", packet)
        self.assertIn("http://101.133.224.223/", packet)
        self.assertIn("passed judge smoke", packet)
        self.assertIn("Public repo readiness", packet)
        self.assertIn("publish the sanitized bundle boundary", packet)
        self.assertIn("do not push the raw workspace", packet)
        self.assertIn("M50 external benchmark and winner polish", packet)
        self.assertIn("internal research/audit notes are excluded from the sanitized public bundle", packet)
        self.assertIn("docs/submission/demo-video-script.md", packet)
        self.assertIn("Devpost Discussions", packet)
        self.assertIn("Project gallery is not yet published", packet)
        self.assertIn("fresh M98 rerun is checked in as live_e2e_failed", packet)
        self.assertIn("M51 architecture diagram", packet)
        self.assertIn("optional broader benchmark fixtures", packet)
        self.assertIn("docs/submission/architecture-diagram.md", packet)
        self.assertIn("Browser demo -> Python demo backend -> SQLite", packet)
        self.assertIn("Qwen text model -> text-embedding-v4 -> qwen3-rerank", packet)
        self.assertIn("M53 demo media package", packet)
        self.assertIn("docs/submission/demo-media-package.md", packet)
        self.assertIn("recording target 2:20-2:45", packet)
        self.assertIn("local MP4 demo video candidate", packet)
        self.assertIn("no Devpost video URL or upload is recorded", packet)
        self.assertIn("M54 public release gate", packet)
        self.assertIn("docs/submission/public-release-gate.md", packet)
        self.assertIn("approval-only actions remain blocked", packet)
        self.assertIn("publish the sanitized bundle, not the raw workspace", packet)

    def test_review_packet_includes_copy_ready_commands(self):
        packet = build_review_packet(ROOT)

        self.assertIn("PYTHONPATH=src python3 tools/build_demo_data.py", packet)
        self.assertIn("PYTHONPATH=src python3 tools/build_review_packet.py", packet)
        self.assertIn("PYTHONPATH=src python3 tools/build_live_qwen_embedding_baseline_preflight.py", packet)
        self.assertIn("bundle_target=\"dist/recallpack-submission-$(date +%Y%m%d-%H%M%S)\"", packet)
        self.assertIn("PYTHONPATH=src python3 tools/build_submission_bundle.py", packet)
        self.assertNotIn(
            "tools/build_submission_bundle.py --target dist/recallpack-submission\n",
            packet,
        )
        self.assertIn("PYTHONPATH=src python3 -m unittest discover -s tests -v", packet)
        self.assertIn('PYTHONPATH=src python3 tools/fresh_clone_smoke.py --source "$bundle_target" --full', packet)
        self.assertIn("PYTHONPATH=src python3 -m recallpack.demo_server", packet)
        self.assertIn("python3 tools/judge_smoke.py --url http://127.0.0.1:8789", packet)
        self.assertIn("curl http://127.0.0.1:8789/api/health", packet)
        self.assertIn("curl -X POST http://127.0.0.1:8789/compile", packet)

    def test_review_packet_can_include_live_qwen_contract_trace(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            trace_path = Path(temp_dir) / "live-qwen-trace.json"
            trace_path.write_text(
                """
{
  "actual_qwen_token_usage": {
    "embedding_total_tokens": 15,
    "memory_decision_total_tokens": 32,
    "rerank_total_tokens": 13
  },
  "live_qwen_run": true,
  "live_status": "live_contract_passed",
  "provider_traces": [
    {
      "deterministic_fallback_status": "live_qwen",
      "input_item_count": 2,
      "input_token_estimate": 40,
      "is_live": true,
      "model_name": "qwen-plus",
      "output_item_count": 1,
      "provider_role": "memory_decision",
      "request_id_present": true,
      "request_purpose": "extract_classify_and_judge_memory_lifecycle"
    },
    {
      "deterministic_fallback_status": "live_qwen",
      "input_item_count": 1,
      "input_token_estimate": 12,
      "is_live": true,
      "model_name": "text-embedding-v4",
      "output_item_count": 1,
      "provider_role": "embedding",
      "request_id_present": true,
      "request_purpose": "candidate_memory_retrieval_query"
    },
    {
      "deterministic_fallback_status": "live_qwen",
      "input_item_count": 1,
      "input_token_estimate": 16,
      "is_live": true,
      "model_name": "qwen3-rerank",
      "output_item_count": 1,
      "provider_role": "rerank",
      "request_id_present": true,
      "request_purpose": "precision_rerank_active_memory_candidates"
    }
  ]
}
""".strip()
            )

            packet = build_review_packet(ROOT, live_qwen_trace_path=trace_path)

        self.assertIn(
            "standalone live API smoke passed: yes, sanitized contract trace recorded",
            packet,
        )
        self.assertIn("actual Qwen token usage: memory=32 embedding=15 rerank=13", packet)
        self.assertIn(
            "recorded Qwen trace status: standalone live API smoke passed (stored status value: live_contract_passed)",
            packet,
        )
        self.assertIn("memory_decision -> qwen-plus", packet)
        self.assertIn("live=True", packet)
        self.assertIn("Live Qwen contract was run once with explicit approval", packet)
        self.assertIn("stores only sanitized trace records", packet)


if __name__ == "__main__":
    unittest.main()
