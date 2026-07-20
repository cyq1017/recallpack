# RecallPack Gated Action Runbook

Use this only after the corresponding row in
`docs/submission/gated-action-approval-matrix.md` is explicitly approved.

## Shared Preflight

Run before any approved gated action:

```bash
PYTHONPATH=src python3 tools/build_demo_data.py
PYTHONPATH=src python3 tools/build_live_qwen_e2e_preflight.py
PYTHONPATH=src python3 tools/build_review_packet.py
python3 -m py_compile tests/test_observe_idempotency.py tests/test_budget.py tests/test_write_candidates.py tests/test_sqlite_event_store.py tests/test_observe_lifecycle.py tests/test_compile.py tests/test_providers.py tests/test_qwen_live_contract.py tests/test_qwen_live_e2e.py tests/test_qwen_live_embedding_baseline.py tests/test_hero_evaluation.py tests/test_micro_suite.py tests/test_demo.py tests/test_demo_server.py tests/test_judge_smoke.py tests/test_submission_packet.py tests/test_submission_docs.py tests/test_submission_bundle.py tools/build_demo_data.py tools/build_review_packet.py tools/build_submission_bundle.py tools/fresh_clone_smoke.py tools/judge_smoke.py tools/run_live_qwen_contract.py tools/run_live_qwen_e2e.py tools/build_live_qwen_e2e_preflight.py tools/run_live_qwen_embedding_baseline.py tools/build_live_qwen_embedding_baseline_preflight.py tools/capture_demo_screenshots.py tools/devpost_preflight.py tools/export_devpost_materials.py tools/export_evidence_index.py tools/final_submission_gate.py tools/public_repo_preflight.py tools/video_rehearsal_gate.py src/recallpack/*.py
PYTHONPATH=src python3 -m unittest discover -s tests -v
node --check web/app.js
```

Stop before any action if the preflight is not green.

The live E2E preflight above is credential-free. It must produce
`docs/submission/live-qwen-e2e-preflight.json` with
`preflight_status = ready_for_live_e2e_rerun`, `network_calls_made=false`, and
`request_role_counts = memory_decision=12 embedding=16 rerank=2 patch_generation=2` before any
approved live E2E rerun.

## Live Qwen Contract

Requires approval for credential access and live Qwen contract execution.

Expected environment shape after approval:

```bash
read -s DASHSCOPE_API_KEY
export DASHSCOPE_API_KEY
export RECALLPACK_ENABLE_LIVE_QWEN=1
export RECALLPACK_LIVE_QWEN_APPROVED=1
export RECALLPACK_QWEN_BASE_URL="https://dashscope.aliyuncs.com/compatible-mode/v1"
export RECALLPACK_QWEN_RERANK_BASE_URL="https://dashscope.aliyuncs.com/compatible-api/v1"
```

Execution:

```bash
PYTHONPATH=src python3 tools/run_live_qwen_contract.py
PYTHONPATH=src python3 tools/build_demo_data.py
PYTHONPATH=src python3 tools/build_review_packet.py
```

Verification:

- `docs/submission/live-qwen-trace.json` must report
  `live_status = live_contract_passed`.
- Provider trace records must include memory_decision, embedding, and rerank.
- Actual Qwen token usage must appear in the review packet and readiness report.
- Scan the trace file for credential, raw prompt, raw memory, or tool argument
  leakage before packaging.

Rollback:

- Unset live Qwen environment variables.
- Do not persist credentials in repo files.

Stop before:

- reading unrelated credentials;
- making non-contract model calls;
- continuing after repeated auth, billing, or schema failures.

## Live Qwen E2E Observe/Compile

Requires separate approval for credential access and live Qwen E2E execution.

Current status: the latest approved run wrote
`docs/submission/live-qwen-e2e-trace.json` with `live_e2e_passed`. M47 hardened
the memory-decision contract with structured event metadata, must-write policy,
and descriptive tool schema fields. M48/M64 add a credential-free preflight for
that hardened contract. Future live reruns still require approval because they
read credentials and consume API quota.

Credential-free preflight:

```bash
PYTHONPATH=src python3 tools/build_live_qwen_e2e_preflight.py
```

Expected preflight output:

- `preflight_status=ready_for_live_e2e_rerun`
- `network_calls_made=false`
- `request_role_counts=memory_decision=12 embedding=16 rerank=2 patch_generation=2`

Expected environment shape after approval:

```bash
read -s DASHSCOPE_API_KEY
export DASHSCOPE_API_KEY
export RECALLPACK_ENABLE_LIVE_QWEN=1
export RECALLPACK_LIVE_QWEN_E2E_APPROVED=1
export RECALLPACK_QWEN_BASE_URL="https://dashscope.aliyuncs.com/compatible-mode/v1"
export RECALLPACK_QWEN_RERANK_BASE_URL="https://dashscope.aliyuncs.com/compatible-api/v1"
```

Execution:

```bash
PYTHONPATH=src python3 tools/run_live_qwen_e2e.py
PYTHONPATH=src python3 tools/build_demo_data.py
PYTHONPATH=src python3 tools/build_review_packet.py
```

Verification:

- `docs/submission/live-qwen-e2e-trace.json` must report
  `live_status = live_e2e_passed`.
- Selected sources must include `session-a:turn-005` and
  `session-a:turn-003`.
- Selected sources must exclude stale `session-a:turn-001`.
- Provider trace records must include memory_decision, embedding, and rerank.
- Scan the trace file for credential, raw prompt, raw memory, or tool argument
  leakage before packaging.

## Docker Build/Run Proof

Requires approval for local Docker build/run proof.

Execution:

```bash
docker build -f deploy/alibaba-cloud/Dockerfile -t recallpack-demo:local .
docker run --rm -p 8789:8789 -v recallpack-data:/data recallpack-demo:local
```

Verification from another shell:

```bash
curl -I http://127.0.0.1:8789/
curl http://127.0.0.1:8789/api/demo
curl -X POST http://127.0.0.1:8789/compile \
  -H 'content-type: application/json' \
  -d '{"project_id":"project-a","goal":"Update the retry helper to the current project policy.","component":"retry","budget_tokens":512}'
```

Rollback:

```bash
docker stop <container-id>
docker image rm recallpack-demo:local
```

Stop before:

- pushing an image;
- accepting privileged prompts;
- changing Dockerfile to include secrets.

## Alibaba Cloud ECS Deployment

Requires approval for Alibaba Cloud account, region, budget, and public access
policy.

Runtime constraints:

```text
deployment_replicas = 1
application_workers = 1
```

Deployment outline:

1. Build or pull the approved image.
2. Start one ECS instance or one container deployment.
3. Mount SQLite data at `/data/recallpack.sqlite3`.
4. Run `recallpack.demo_server` on port `8789`.
5. Expose only the approved endpoint and duration.

Verification:

```bash
curl -I http://APPROVED_HOST:8789/
curl http://APPROVED_HOST:8789/api/demo
curl -X POST http://APPROVED_HOST:8789/compile \
  -H 'content-type: application/json' \
  -d '{"project_id":"project-a","goal":"Update the retry helper to the current project policy.","component":"retry","budget_tokens":512}'
```

rollback:

1. Remove the public endpoint.
2. Stop the container.
3. Stop or release the ECS instance.
4. Confirm the endpoint no longer responds.

Stop before:

- using more than one replica;
- using more than one application worker;
- exposing a public endpoint without an approved duration;
- storing credentials in the image or repo.

## Hackathon Submission

Requires approval for the exact submission destination and fields.

Copy-ready local sources:

- `docs/submission/hackathon-fields.md`
- `docs/submission/review-packet.md`
- `docs/submission/local-readiness-report.md`
- `docs/deployment/alibaba-cloud-proof.md`

Verification:

- Confirm the form destination.
- Confirm every field value with the user before submit.
- Confirm any uploaded screenshots/video links are intended for public review.

rollback:

- If the platform allows editing, correct the submission fields.
- If the platform does not allow editing, prepare a corrected follow-up note.

Stop before:

- submitting without final field review;
- uploading private files;
- making the repo public;
- claiming live deployment if it has not been approved and completed.
