# RecallPack Submission Bundle Manifest

Generated locally for hackathon review/submission packaging.
This bundle is intentionally narrower than the working directory.

## Included Files

- `.gitignore`
- `LICENSE`
- `README.md`
- `deploy/alibaba-cloud/Dockerfile`
- `docs/deployment/alibaba-cloud-proof.md`
- `docs/plans/2026-06-24-recallpack-v3.2.2.md`
- `docs/submission/architecture-diagram.md`
- `docs/submission/blog-post-draft.md`
- `docs/submission/demo-media-package.md`
- `docs/submission/demo-runbook.md`
- `docs/submission/demo-video-script.md`
- `docs/submission/devpost-final-copy.md`
- `docs/submission/devpost-materials.json`
- `docs/submission/devpost-materials.md`
- `docs/submission/devpost-upload-state.json`
- `docs/submission/evidence-index.json`
- `docs/submission/evidence-index.md`
- `docs/submission/final-judge-rehearsal.md`
- `docs/submission/final-recording-runbook.md`
- `docs/submission/final-video-voiceover-elevenlabs.md`
- `docs/submission/gated-action-approval-matrix.md`
- `docs/submission/gated-action-runbook.md`
- `docs/submission/hackathon-fields.md`
- `docs/submission/judge-surface-reset-plan.md`
- `docs/submission/live-qwen-e2e-preflight.json`
- `docs/submission/live-qwen-e2e-trace.json`
- `docs/submission/live-qwen-embedding-baseline-preflight.json`
- `docs/submission/live-qwen-embedding-baseline-trace.json`
- `docs/submission/live-qwen-m98-embedding-baseline-trace.json`
- `docs/submission/live-qwen-m98-rerun-trace.json`
- `docs/submission/live-qwen-trace.json`
- `docs/submission/local-readiness-report.md`
- `docs/submission/media/01-first-run-handoff-simulator.png`
- `docs/submission/media/02-recallpack-active-memory-pack.png`
- `docs/submission/media/03-qwen-provider-evidence.png`
- `docs/submission/media/README.md`
- `docs/submission/media/alibaba-cloud-deployment-proof-redacted.png`
- `docs/submission/media/architecture-diagram.png`
- `docs/submission/media/m71-replay/01-one-click-stale-memory-replay.png`
- `docs/submission/media/m71-replay/02-recallpack-active-memory-pack.png`
- `docs/submission/media/m71-replay/03-qwen-provider-evidence.png`
- `docs/submission/media/recallpack-judge-deck.pptx`
- `docs/submission/media/video-candidate/README.md`
- `docs/submission/media/video-candidate/manifest.json`
- `docs/submission/media/video-candidate/recallpack-demo-candidate.mp4`
- `docs/submission/media/video-candidate/voiceover.txt`
- `docs/submission/projectodyssey-dry-run.md`
- `docs/submission/projectodyssey-live-qwen-e2e-preflight.json`
- `docs/submission/projectodyssey-live-qwen-e2e-trace.json`
- `docs/submission/public-release-gate.md`
- `docs/submission/public-repo-readiness-report.md`
- `docs/submission/recording-rehearsal-report.json`
- `docs/submission/recording-rehearsal-report.md`
- `docs/submission/review-packet.md`
- `docs/submission/skeptical-judge-qa.md`
- `docs/submission/submission-checklist.md`
- `docs/submission/video-production-packet.md`
- `evaluation/.dockerignore`
- `evaluation/Dockerfile`
- `evaluation/hidden-tests/deepagents/manifest.json`
- `evaluation/hidden-tests/deepagents/tests/__init__.py`
- `evaluation/hidden-tests/deepagents/tests/test_package_policy.py`
- `evaluation/hidden-tests/graphiti/manifest.json`
- `evaluation/hidden-tests/graphiti/tests/__init__.py`
- `evaluation/hidden-tests/graphiti/tests/test_backend_policy.py`
- `evaluation/hidden-tests/projectodyssey/manifest.json`
- `evaluation/hidden-tests/projectodyssey/tests/__init__.py`
- `evaluation/hidden-tests/projectodyssey/tests/test_ci_policy.py`
- `evaluation/runner/run_tests.py`
- `evaluation/scenarios/deepagents/authored-events.jsonl`
- `evaluation/scenarios/deepagents/leakage-review.json`
- `evaluation/scenarios/deepagents/provenance.json`
- `evaluation/scenarios/deepagents/relation-label-ledger.json`
- `evaluation/scenarios/deepagents/source-ledger.json`
- `evaluation/scenarios/graphiti/authored-events.jsonl`
- `evaluation/scenarios/graphiti/leakage-review.json`
- `evaluation/scenarios/graphiti/provenance.json`
- `evaluation/scenarios/graphiti/relation-label-ledger.json`
- `evaluation/scenarios/graphiti/source-ledger.json`
- `evaluation/scenarios/projectodyssey/authored-events.jsonl`
- `evaluation/scenarios/projectodyssey/leakage-review.json`
- `evaluation/scenarios/projectodyssey/provenance.json`
- `evaluation/scenarios/projectodyssey/relation-label-ledger.json`
- `evaluation/scenarios/projectodyssey/source-ledger.json`
- `fixtures/micro-suite/suite.json`
- `fixtures/project-a/gold.json`
- `fixtures/project-a/repo_snapshot/README.md`
- `fixtures/project-a/repo_snapshot/pyproject.toml`
- `fixtures/project-a/repo_snapshot/src/retry.py`
- `fixtures/project-a/sessions.jsonl`
- `fixtures/project-b/gold.json`
- `fixtures/project-b/repo_snapshot/README.md`
- `fixtures/project-b/repo_snapshot/pyproject.toml`
- `fixtures/project-b/repo_snapshot/src/config_loader.py`
- `fixtures/project-b/sessions.jsonl`
- `fixtures/project-c/gold.json`
- `fixtures/project-c/repo_snapshot/README.md`
- `fixtures/project-c/repo_snapshot/pyproject.toml`
- `fixtures/project-c/repo_snapshot/src/cache_policy.py`
- `fixtures/project-c/sessions.jsonl`
- `fixtures/project-d/gold.json`
- `fixtures/project-d/repo_snapshot/README.md`
- `fixtures/project-d/repo_snapshot/pyproject.toml`
- `fixtures/project-d/repo_snapshot/src/audit_serializer.py`
- `fixtures/project-d/sessions.jsonl`
- `fixtures/project-e/gold.json`
- `fixtures/project-e/repo_snapshot/README.md`
- `fixtures/project-e/repo_snapshot/pyproject.toml`
- `fixtures/project-e/repo_snapshot/src/pagination.py`
- `fixtures/project-e/sessions.jsonl`
- `fixtures/project-f-realistic/gold.json`
- `fixtures/project-f-realistic/provenance.md`
- `fixtures/project-f-realistic/repo_snapshot/README.md`
- `fixtures/project-f-realistic/repo_snapshot/pyproject.toml`
- `fixtures/project-f-realistic/repo_snapshot/src/api_client.py`
- `fixtures/project-f-realistic/sessions.jsonl`
- `fixtures/project-g-auth-mode/gold.json`
- `fixtures/project-g-auth-mode/provenance.md`
- `fixtures/project-g-auth-mode/repo_snapshot/README.md`
- `fixtures/project-g-auth-mode/repo_snapshot/pyproject.toml`
- `fixtures/project-g-auth-mode/repo_snapshot/src/provider_auth.py`
- `fixtures/project-g-auth-mode/sessions.jsonl`
- `fixtures/project-h-projectodyssey-jit/gold.json`
- `fixtures/project-h-projectodyssey-jit/provenance.md`
- `fixtures/project-h-projectodyssey-jit/repo_snapshot/README.md`
- `fixtures/project-h-projectodyssey-jit/repo_snapshot/pyproject.toml`
- `fixtures/project-h-projectodyssey-jit/repo_snapshot/src/ci_policy.py`
- `fixtures/project-h-projectodyssey-jit/sessions.jsonl`
- `fixtures/project-i-deepagents-package/gold.json`
- `fixtures/project-i-deepagents-package/repo_snapshot/pyproject.toml`
- `fixtures/project-i-deepagents-package/repo_snapshot/src/package_policy.py`
- `fixtures/project-j-graphiti-backend/gold.json`
- `fixtures/project-j-graphiti-backend/repo_snapshot/pyproject.toml`
- `fixtures/project-j-graphiti-backend/repo_snapshot/src/backend_policy.py`
- `fixtures/trace-intake/sample-consent-trace.json`
- `requirements-v4.txt`
- `specs/001-recallpack-v4/contracts/artifacts.schema.json`
- `specs/001-recallpack-v4/contracts/compile.openapi.yaml`
- `specs/001-recallpack-v4/contracts/evaluation.schema.json`
- `specs/001-recallpack-v4/contracts/observe.openapi.yaml`
- `specs/001-recallpack-v4/contracts/review-json-golden-vectors.json`
- `specs/001-recallpack-v4/contracts/review-seed-contract.md`
- `specs/001-recallpack-v4/contracts/review-seed-generation-command.md`
- `specs/001-recallpack-v4/contracts/review-seed.schema.json`
- `specs/001-recallpack-v4/review-seed-operator-runbook.md`
- `specs/001-recallpack-v4/reviews/t053-external-review-phase2-prompt-v4.md`
- `specs/001-recallpack-v4/reviews/t053-phase2-custody-report.schema.v4.json`
- `specs/001-recallpack-v4/reviews/t053-proposed-events-v3.json`
- `specs/001-recallpack-v4/reviews/t053-review-source-inventory-v3.json`
- `specs/001-recallpack-v4/reviews/t053-semantic-adjudication-report.schema.v4.json`
- `specs/001-recallpack-v4/reviews/t053-semantic-adjudication-vectors-v4.json`
- `src/recallpack/__init__.py`
- `src/recallpack/artifacts.py`
- `src/recallpack/budget.py`
- `src/recallpack/compile.py`
- `src/recallpack/demo.py`
- `src/recallpack/demo_server.py`
- `src/recallpack/downstream.py`
- `src/recallpack/downstream_contract.py`
- `src/recallpack/evaluation.py`
- `src/recallpack/evaluation_docker.py`
- `src/recallpack/evaluation_evidence_adapter.py`
- `src/recallpack/evaluation_v4.py`
- `src/recallpack/evaluation_variants.py`
- `src/recallpack/evidence.py`
- `src/recallpack/evidence_aggregate.py`
- `src/recallpack/evidence_authority.py`
- `src/recallpack/evidence_common.py`
- `src/recallpack/evidence_custody.py`
- `src/recallpack/evidence_execution_manifest.py`
- `src/recallpack/evidence_manifest.py`
- `src/recallpack/evidence_manifest_claims.py`
- `src/recallpack/evidence_pipeline.py`
- `src/recallpack/evidence_review_protocol.py`
- `src/recallpack/evidence_run.py`
- `src/recallpack/evidence_run_relations.py`
- `src/recallpack/evidence_run_support.py`
- `src/recallpack/isolation.py`
- `src/recallpack/live_qwen_contract.py`
- `src/recallpack/live_qwen_e2e.py`
- `src/recallpack/live_qwen_embedding_baseline.py`
- `src/recallpack/locking.py`
- `src/recallpack/memory.py`
- `src/recallpack/observe.py`
- `src/recallpack/providers.py`
- `src/recallpack/review_json.py`
- `src/recallpack/review_seed_draft.py`
- `src/recallpack/review_seed_generation.py`
- `src/recallpack/secure_files.py`
- `src/recallpack/storage.py`
- `src/recallpack/submission_bundle.py`
- `src/recallpack/submission_packet.py`
- `src/recallpack/testing.py`
- `src/recallpack/tokenization.py`
- `src/recallpack/trace_intake.py`
- `src/recallpack/v4_live_execution.py`
- `src/recallpack/write_candidates.py`
- `tests/_v41_eligible_registry.py`
- `tests/_v41_review_seed_fixtures.py`
- `tests/_v4_evidence_aggregate_fixtures.py`
- `tests/_v4_evidence_common.py`
- `tests/_v4_evidence_manifest_final_fixtures.py`
- `tests/_v4_evidence_manifest_fixtures.py`
- `tests/_v4_evidence_run_fixtures.py`
- `tests/test_budget.py`
- `tests/test_compile.py`
- `tests/test_compile_artifacts.py`
- `tests/test_demo.py`
- `tests/test_demo_server.py`
- `tests/test_demo_video_candidate.py`
- `tests/test_downstream_contract.py`
- `tests/test_downstream_isolation.py`
- `tests/test_evaluation_scenarios.py`
- `tests/test_evaluator_runner.py`
- `tests/test_evidence_aggregate_edge_cases.py`
- `tests/test_evidence_aggregate_metrics.py`
- `tests/test_evidence_aggregate_prerequisites.py`
- `tests/test_evidence_manifest.py`
- `tests/test_evidence_manifest_contract_edges.py`
- `tests/test_evidence_run_validation.py`
- `tests/test_hero_evaluation.py`
- `tests/test_judge_smoke.py`
- `tests/test_micro_suite.py`
- `tests/test_observe_idempotency.py`
- `tests/test_observe_lifecycle.py`
- `tests/test_observe_repair.py`
- `tests/test_project_serialization.py`
- `tests/test_providers.py`
- `tests/test_qwen_live_contract.py`
- `tests/test_qwen_live_e2e.py`
- `tests/test_qwen_live_embedding_baseline.py`
- `tests/test_real_trace_intake.py`
- `tests/test_review_seed_custody.py`
- `tests/test_review_seed_draft.py`
- `tests/test_review_seed_generation.py`
- `tests/test_review_seed_protocol.py`
- `tests/test_review_seed_semantics.py`
- `tests/test_sqlite_event_store.py`
- `tests/test_storage_migrations.py`
- `tests/test_submission_bundle.py`
- `tests/test_submission_docs.py`
- `tests/test_submission_packet.py`
- `tests/test_t053_v4_remediation.py`
- `tests/test_v4_contracts.py`
- `tests/test_v4_docker_diagnostics.py`
- `tests/test_v4_hidden_suites.py`
- `tests/test_v4_live_execution.py`
- `tests/test_v4_variant_execution.py`
- `tests/test_write_candidates.py`
- `tests/v4_evidence_fixtures.py`
- `tools/build_demo_data.py`
- `tools/build_demo_video_candidate.py`
- `tools/build_external_review_zip.py`
- `tools/build_live_qwen_e2e_preflight.py`
- `tools/build_live_qwen_embedding_baseline_preflight.py`
- `tools/build_review_packet.py`
- `tools/build_review_seed_draft.py`
- `tools/build_submission_bundle.py`
- `tools/capture_demo_screenshots.py`
- `tools/devpost_preflight.py`
- `tools/export_devpost_materials.py`
- `tools/export_evidence_index.py`
- `tools/final_submission_gate.py`
- `tools/fresh_clone_smoke.py`
- `tools/generate_review_seed.py`
- `tools/judge_smoke.py`
- `tools/public_repo_preflight.py`
- `tools/run_live_qwen_contract.py`
- `tools/run_live_qwen_e2e.py`
- `tools/run_live_qwen_embedding_baseline.py`
- `tools/submission_readiness_loop.py`
- `tools/validate_real_trace_intake.py`
- `tools/verify_review_json_vectors.mjs`
- `tools/video_rehearsal_gate.py`
- `web/app.js`
- `web/demo-data.js`
- `web/index.html`
- `web/styles.css`

## Excluded From Bundle

- `AGENTS.md`
- `docs/execution/`
- `docs/research/`
- `docs/submission/internal-audits-and-milestone-notes`
- `docs/submission/media/alibaba-cloud-deployment-proof.png`
- `dist/`
- `__pycache__/`
- `*.pyc`
- `.DS_Store`
- `*.inspect.ndjson`

## Judge Quick Checks

RecallPack is a MemoryAgent submission. The local review path proves stale-aware
memory lifecycle, budgeted recall, downstream patch/test behavior, and the
Qwen load-bearing boundary without requiring live credentials.

No credentials are required for local checks.

Truthfulness boundary: local hidden-test proof uses a local
deterministic context-keyed patch provider; local raw-history
baseline retrieval uses keyword-scored fake embeddings/rerank;
the 32-event micro-suite is a behavior contract fixture suite;
and live Qwen evidence is a stored sanitized one-run trace.
The local Docker is the canonical credential-free demo surface.
The public ECS endpoint is an approved deployment proof
and may be revalidated separately, but local Docker is the
canonical credential-free demo surface for judging.
The full fresh-clone rehearsal runs public-test discovery.
Custody-bound frozen-executor tests explicitly skip because their
private frozen execution manifest is intentionally excluded from
this public bundle; the private workspace runs that custody suite.

From this bundle root:

```bash
PYTHONPATH=src python3 tools/build_live_qwen_e2e_preflight.py
PYTHONPATH=src python3 tools/build_live_qwen_embedding_baseline_preflight.py
python3 -m venv .venv
. .venv/bin/activate
python3 -m pip install -r requirements-v4.txt
PYTHONPATH=src python3 tools/fresh_clone_smoke.py --source .
PYTHONPATH=src python3 tools/fresh_clone_smoke.py --source . --full
PYTHONPATH=src python3 -m unittest discover -s tests -v
node --check web/app.js
python3 tools/devpost_preflight.py
python3 tools/export_devpost_materials.py
python3 tools/export_evidence_index.py
python3 tools/video_rehearsal_gate.py
python3 tools/final_submission_gate.py
python3 tools/public_repo_preflight.py
python3 tools/submission_readiness_loop.py --full
```

The live E2E preflight is credential-free and records no-network
readiness for the next explicitly approved live Qwen rerun.
The real embedding baseline preflight is also credential-free and
verifies the text-embedding-v4 plus qwen3-rerank raw-history
baseline request path before any approved live baseline run.
The Devpost preflight is also credential-free and reports local
material readiness versus manual gated submission actions.
The Devpost materials export is local-only and turns checked-in
submission copy, media assets, and preflight blockers into JSON
and Markdown for manual copy/paste.
The evidence index maps judge-facing claims to files and commands
without making network calls or public changes.
The final submission gate aggregates preflight, evidence index,
bundle scan, and full fresh-clone rehearsal into one local report.
The public repo preflight checks the sanitized publish surface,
license, README, manifest, forbidden paths, and judge commands
before or after public GitHub repository creation.

When the local demo server is running on `127.0.0.1:8789`:

```bash
curl http://127.0.0.1:8789/api/health
python3 tools/judge_smoke.py --url http://127.0.0.1:8789
```

Primary API surface:

- `GET /api/health` gives the compact judging readiness summary.
- `GET /api/demo` returns the full demo/evaluation payload.
- `POST /observe` records ordered memory lifecycle events.
- `POST /compile` returns the active memory pack under budget.

## Safety Notes

- No live Qwen credentials are read or copied.
- No public deployment or hackathon submission is performed by this builder.
- Existing target directories are not overwritten by default.
