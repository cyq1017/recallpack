# RecallPack Demo Runbook

Use this runbook for local rehearsal only. It does not authorize additional
live Qwen reruns, public deployment, image push, or hackathon submission.

## 1. Refresh Generated Artifacts

```bash
PYTHONPATH=src python3 tools/build_demo_data.py
PYTHONPATH=src python3 tools/build_live_qwen_e2e_preflight.py
PYTHONPATH=src python3 tools/build_live_qwen_embedding_baseline_preflight.py
PYTHONPATH=src python3 tools/build_review_packet.py
```

Also keep `docs/submission/skeptical-judge-qa.md` open during rehearsal; it is
the claim-to-evidence map for hard judge questions.

## 2. Verify Local Suite

```bash
python3 -m py_compile \
  tests/test_observe_idempotency.py tests/test_budget.py \
  tests/test_write_candidates.py tests/test_sqlite_event_store.py \
  tests/test_observe_lifecycle.py tests/test_compile.py tests/test_providers.py \
  tests/test_qwen_live_contract.py tests/test_qwen_live_e2e.py \
  tests/test_qwen_live_embedding_baseline.py tests/test_hero_evaluation.py \
  tests/test_micro_suite.py tests/test_demo.py tests/test_demo_server.py \
  tests/test_judge_smoke.py tests/test_submission_packet.py \
  tests/test_submission_docs.py tests/test_submission_bundle.py \
  tools/build_demo_data.py tools/build_review_packet.py \
  tools/build_submission_bundle.py tools/build_external_review_zip.py tools/fresh_clone_smoke.py \
  tools/judge_smoke.py tools/run_live_qwen_contract.py \
  tools/run_live_qwen_e2e.py tools/build_live_qwen_e2e_preflight.py \
  tools/run_live_qwen_embedding_baseline.py \
  tools/build_live_qwen_embedding_baseline_preflight.py \
  tools/capture_demo_screenshots.py tools/devpost_preflight.py \
  tools/export_devpost_materials.py tools/export_evidence_index.py \
  tools/final_submission_gate.py tools/public_repo_preflight.py \
  tools/video_rehearsal_gate.py src/recallpack/*.py
PYTHONPATH=src python3 -m unittest discover -s tests -v
node --check web/app.js
```

Expected:

- Python compile exits 0.
- Unit test suite passes without requiring live Qwen network access.
- `tests/test_qwen_live_contract.py` validates the live-provider contract with
  fake HTTP responses.
- `tests/test_qwen_live_e2e.py` validates the gated live Qwen E2E
  observe/compile runner with fake HTTP responses.
- `tools/build_live_qwen_e2e_preflight.py` records the credential-free
  no-network preflight before any approved live E2E rerun.
- `tools/build_live_qwen_embedding_baseline_preflight.py` records the
  credential-free no-network preflight for the real `text-embedding-v4` raw
  history baseline before any approved live baseline rerun.
- JavaScript syntax check exits 0.

## 3. Build Sanitized Submission Bundle

```bash
bundle_target="dist/recallpack-submission-$(date +%Y%m%d-%H%M%S)"
PYTHONPATH=src python3 tools/build_submission_bundle.py --target "$bundle_target"
```

Expected:

- command exits 0 from a clean target path;
- scan reports zero local path, secret, generated artifact, and internal path
  hits;
- generated package contains `SUBMISSION_MANIFEST.md`.

The timestamped target avoids overwriting prior local bundles. Get explicit
approval before deleting or replacing an old bundle.

## 4. Start Local Demo

```bash
PYTHONPATH=src python3 -m recallpack.demo_server --host 127.0.0.1 --port 8789
```

Open:

```text
http://127.0.0.1:8789/
```

In a second terminal, run the judge smoke script:

```bash
python3 tools/judge_smoke.py --url http://127.0.0.1:8789
```

Expected: JSON output with `status = passed`,
`health.live_status = live_contract_passed`,
`health.live_qwen_e2e_status = live_e2e_passed`,
`api_demo.fixture_count = 8`, and `compile.excludes_stale_decision = true`.

## 5. Demo Narrative

Learn:

- Open the first screen on Learn and start with the Evidence Boundary: the
  headline is write-time lifecycle exclusion, not live retrieval failure rate.
- State that stored live raw-history embedding+rerank baseline traces selected
  the active retry decision on this fixture; the local 1/3 vs 3/3 replay is an
  authored deterministic failure-class illustration.
- Then use the one-click stale-memory failure replay.
- Click through stale context selected -> wrong retry patch -> active memory
  pack -> passing retry patch.
- Point out that the replay reuses existing downstream temp-repo patch/test
  evidence: baseline fixture tests 1/3 and RecallPack fixture tests 3/3.
- State the truthfulness boundary: the local replay uses a deterministic
  context-keyed patch provider, not live Qwen inference.
- Point to the judge-first comparison strip: raw full-history reference,
  keyword-scored fake-embedding + rerank raw-history baseline, and RecallPack.
- Show the First-Run Handoff Simulator as the compact summary after the replay.
- Use the simulator branches to show that the baseline retrieves stale raw history
  while RecallPack compiles an active memory lifecycle pack.
- Then use the hero story and judge-first comparison strip to summarize the
  raw full-history reference, keyword-scored fake-embedding + rerank
  raw-history baseline, and RecallPack.
- Show keyword-scored fake-embedding + rerank raw-history baseline: fixture tests 1/3.
- State that the raw full-history reference selects all 12 events and is not
  budget-comparable.
- Show RecallPack active memory: fixture tests 3/3.
- Show the `/compile` path: local fake embedding top-N -> fake
  qwen3-rerank-shaped rerank -> estimated 512-token serialized-memory budget
  selector. The live `text-embedding-v4` and `qwen3-rerank` evidence is the
  stored sanitized E2E trace.
- State that the checked-in local demo uses the approved sanitized standalone
  live API smoke trace with stored status `live_contract_passed`.
- Point to the first-screen Qwen status lines:
  "Standalone Qwen API smoke: passed",
  "Stored live provider-path E2E: one pass; fresh rerun failed", and
  "Lifecycle filtering: held in stored live runs".
- State that local tests do not read credentials: fake providers and sanitized
  trace records cover the review-facing Qwen contract.
- State that `tools/run_live_qwen_e2e.py` produced the sanitized passing live
  observe/compile/patch-generation trace, and future reruns still require
  `RECALLPACK_LIVE_QWEN_E2E_APPROVED=1`.
- State that `tools/build_live_qwen_e2e_preflight.py` already exercises the
  hardened path without credentials and reports
  `preflight_status=ready_for_live_e2e_rerun`.
- State that `tools/build_live_qwen_embedding_baseline_preflight.py` checks the
  real `text-embedding-v4` + `qwen3-rerank` raw-history baseline request shape
  without credentials; the live baseline rerun remains gated.
- Show the 12 ordered session events.
- Point out the old retry decision and the later replacement decision.
- Show active vs superseded lifecycle state.

Recall:

- Show raw full-history reference as a coverage upper bound, not the headline
  baseline.
- Show keyword-scored fake-embedding + rerank raw-history selection picking
  stale retry memory from event text, not fixture-selected source IDs.
- Show RecallPack selecting the active retry decision and project preference.
- Show that `/compile` uses embedding top-N retrieval before rerank and budget
  selection.
- State that local HTTP `/compile` uses deterministic keyword fake
  embedding/rerank providers, not zero-vector or identity-rerank smoke.
- Emphasize the estimated 512-token serialized-memory segment.

Evaluate:

- Show the 32-event micro-suite.
- Show the eight curated lifecycle fixtures: project-a retry, project-b config
  loader, project-c cache policy, project-d audit serializer, project-e
  pagination, project-f API-client auth, project-g provider-auth mode, and
  project-h ProjectOdyssey JIT policy all have baseline 1/3 and RecallPack 3/3.
- Read raw counts before rates.
- Show 10/10 supersession edge correctness and zero stale selected items.
- Show the Qwen Provider Integration Evidence section.
- Point out memory_decision, embedding, and rerank trace records.
- State that the local unit tests use fake providers matching the live-provider
  schema, while `docs/submission/live-qwen-trace.json` stores the approved
  live contract proof.

Deployment proof:

- Open `docs/deployment/alibaba-cloud-proof.md`.
- Show the ECS + Docker + SQLite target.
- State the fixed `deployment_replicas = 1` and `application_workers = 1`.

## 6. API Smoke Checks

```bash
curl -I http://127.0.0.1:8789/
curl http://127.0.0.1:8789/api/health
curl http://127.0.0.1:8789/api/demo
curl -X POST http://127.0.0.1:8789/observe \
  -H 'content-type: application/json' \
  -d '{"project_id":"project-a","session_id":"session-a","event_id":"turn-001","sequence_no":1,"actor":"user","kind":"message","observed_at":"2026-06-24T00:00:00Z","text":"Use three attempts with a fixed 100 ms delay in the retry helper."}'
curl -X POST http://127.0.0.1:8789/compile \
  -H 'content-type: application/json' \
  -d '{"project_id":"project-a","goal":"Update the retry helper to the current project policy.","component":"retry","budget_tokens":512}'
```

Expected `/compile` result includes:

- `session-a:turn-005`
- `session-a:turn-003`
- `trace.local_provider_mode = deterministic_keyword_fake`

Expected `/compile` result excludes:

- `session-a:turn-001`

## Stop Rules

Stop before:

- reading or using credentials for any additional run;
- rerunning live Qwen tests or contract calls;
- running public Alibaba Cloud resources;
- pushing container images;
- exposing a public endpoint;
- submitting the hackathon project.
