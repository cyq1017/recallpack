# RecallPack Submission Checklist

This checklist is the local readiness gate before any public action.

## Local Readiness

- [x] `PYTHONPATH=src python3 tools/build_demo_data.py` rerun.
- [x] `PYTHONPATH=src python3 tools/build_review_packet.py` rerun.
- [x] Python compile command in `docs/submission/demo-runbook.md` exits 0.
- [x] `PYTHONPATH=src python3 -m unittest discover -s tests -v` passes.
- [x] `node --check web/app.js` exits 0.
- [x] `bundle_target="dist/recallpack-submission-$(date +%Y%m%d-%H%M%S)"` is set for a fresh local bundle target.
- [x] `PYTHONPATH=src python3 tools/build_submission_bundle.py --target "$bundle_target"` exits 0.
- [x] Sanitized bundle scan reports zero local path, secret, generated artifact,
  and internal path hits.
- [x] MIT `LICENSE` is present.
- [x] `docs/submission/public-repo-readiness-report.md` defines the public repo
  boundary.
- [x] Local Docker build/run proof passed on `127.0.0.1`.
- [x] Local demo opens at `http://127.0.0.1:8789/`.
- [x] `/api/demo` returns a 32-event micro-suite.
- [x] `/compile` includes active `session-a:turn-005`.
- [x] `/compile` excludes stale `session-a:turn-001`.

## Story Readiness

- [x] First sentence says MemoryAgent, not generic RAG.
- [x] Demo starts with stale handoff failure.
- [x] Demo shows lifecycle state: active vs superseded.
- [x] Qwen provider integration path names embedding, rerank, and text-model judgment.
- [x] Qwen provider integration trace evidence shows memory_decision, embedding, and
  rerank records with the approved sanitized live Qwen contract trace.
- [x] `/compile` uses embedding top-N retrieval before rerank and budget
  selection.
- [x] Baseline comparison includes raw full-history reference plus computed
  embedding top-k RAG, not fixture-selected source IDs.
- [x] Judge first-screen summary distinguishes baseline, RecallPack, Qwen model
  work, deterministic runtime work, and downstream temp-repo proof.
- [x] First-screen Qwen status distinguishes standalone API smoke passed from
  live observe/compile E2E passed.
- [x] Evaluate view includes eight project fixtures under one downstream
  contract.
- [x] Evaluate view records mixed adverse baseline outcomes: 1/3 where a stale patch is produced and 0/3 with `empty_patch` where strict validation rejects a no-op.
- [x] Deterministic runtime boundaries are explicit.
- [x] Micro-suite is described as a hackathon evidence suite, not a benchmark.
- [x] Alibaba Cloud ECS public demo deployment passed judge smoke at
  `http://101.133.224.223/`.
- [x] Latest live Qwen E2E trace passed with
  `live_qwen_e2e_status=live_e2e_passed`.

## Safety Gates

These require explicit user approval in the current task:

- [x] One-time Live Qwen credential access for the contract trace.
- [x] One-time Live Qwen contract execution.
- [ ] Any additional Live Qwen credential access or contract rerun.
- [x] One-time local Docker build/run proof.
- [x] Approved Alibaba Cloud Docker run on port 80 with volume
  `recallpack-data`.
- [x] Approved M102 ECS Docker redeploy with the latest sanitized bundle and
  the same public port scope.
- [ ] Any further Docker run if it changes ports, volumes, or runtime scope.
- [ ] Image push.
- [x] Approved ECS resource creation.
- [x] Approved public endpoint exposure.
- [x] Public GitHub repo created from the sanitized bundle:
  `https://github.com/cyq1017/recallpack`.
- [x] GitHub shows MIT License in the repository About/license area.
- [x] Public repository URL is accessible from a fresh clone and passes judge
  smoke.
- [x] Public repo checks rerun from the public repo root:
  `python3 tools/public_repo_preflight.py`,
  `python3 tools/final_submission_gate.py`, and
  `PYTHONPATH=src python3 tools/fresh_clone_smoke.py --source . --full`.
- [ ] Reconfirm the recorded public repository contains the latest sanitized
  bundle. Local preflight does not prove remote freshness.
- [ ] Upload or link the privacy-checked presentation PPT.
- [ ] Hackathon submission.

## Final Packet Files

- [x] `README.md`
- [x] `LICENSE`
- [x] `.gitignore`
- [x] `docs/submission/review-packet.md`
- [x] `docs/submission/devpost-final-copy.md`
- [x] `docs/submission/demo-video-script.md`
- [x] `docs/submission/blog-post-draft.md`
- [x] `docs/submission/final-judge-rehearsal.md`
- [x] `docs/submission/video-production-packet.md`
- [x] `docs/submission/recording-rehearsal-report.md`
- [x] `docs/submission/demo-media-package.md`
- [x] `docs/submission/media/recallpack-judge-deck.pptx`
- [x] `docs/submission/architecture-diagram.md`
- [x] `docs/submission/skeptical-judge-qa.md`
- [x] `docs/submission/evidence-index.md`
- [x] `docs/submission/devpost-materials.md`
- [x] `docs/submission/public-release-gate.md`
- [x] `docs/submission/demo-runbook.md`
- [x] `docs/submission/submission-checklist.md`
- [x] `docs/submission/local-readiness-report.md`
- [x] `docs/submission/public-repo-readiness-report.md`
- [x] `docs/submission/hackathon-fields.md`
- [x] `docs/submission/gated-action-approval-matrix.md`
- [x] `docs/submission/gated-action-runbook.md`
- [x] `docs/deployment/alibaba-cloud-proof.md`
- [x] `tools/build_submission_bundle.py`
- [x] Fresh timestamped `dist/recallpack-submission-*/SUBMISSION_MANIFEST.md`
- [x] `web/index.html`
- [x] `web/demo-data.js`
- [x] `deploy/alibaba-cloud/Dockerfile`
