# RecallPack M54 Public Release Gate

Status: approval-ready local gate.

No push, publish, public repo creation, image push, or Devpost submission was performed by this document.

## Release Candidate Source

Sanitized bundle only:

```text
dist/recallpack-submission-20260720-231611/
```

Do not publish the raw workspace.

The raw workspace intentionally contains execution notes, generated bundles,
agent instructions, old artifacts, and local-only context that are not part of
the judge-facing repository.

## Must Exclude

The public repository must not include:

- `docs/execution/`
- `AGENTS.md`
- `dist/`
- `__pycache__/`
- `*.pyc`
- `.DS_Store`
- `.env`
- `*.sqlite`
- `*.sqlite3`
- private SSH keys or cloud credentials
- raw terminal logs containing secrets

## Required Public Files

The public repository must include:

- `LICENSE`
- `README.md`
- `.gitignore`
- `requirements-v4.txt`
- `src/recallpack/`
- `tests/`
- `fixtures/`
- `web/`
- `tools/`
- `tools/capture_demo_screenshots.py`
- `tools/devpost_preflight.py`
- `tools/export_devpost_materials.py`
- `tools/export_evidence_index.py`
- `tools/final_submission_gate.py`
- `tools/public_repo_preflight.py`
- `tools/submission_readiness_loop.py`
- `tools/build_external_review_zip.py`
- `deploy/alibaba-cloud/Dockerfile`
- `docs/submission/review-packet.md`
- `docs/submission/public-repo-readiness-report.md`
- `docs/submission/public-release-gate.md`
- `docs/submission/devpost-final-copy.md`
- `docs/submission/demo-runbook.md`
- `docs/submission/demo-video-script.md`
- `docs/submission/demo-media-package.md`
- `docs/submission/video-production-packet.md`
- `docs/submission/recording-rehearsal-report.md`
- `docs/submission/final-judge-rehearsal.md`
- `docs/submission/media/m71-replay/*.png`
- `docs/submission/architecture-diagram.md`
- `docs/submission/skeptical-judge-qa.md`
- `docs/deployment/alibaba-cloud-proof.md`
- `docs/plans/2026-06-24-recallpack-v3.2.2.md`
- `SUBMISSION_MANIFEST.md`

## Final Judge Commands

After public repo creation, run from the public repo root:

```bash
python3 -m venv .venv
. .venv/bin/activate
python3 -m pip install -r requirements-v4.txt
PYTHONPATH=src python3 tools/fresh_clone_smoke.py --source .
PYTHONPATH=src python3 tools/fresh_clone_smoke.py --source . --full
python3 tools/devpost_preflight.py
python3 tools/export_devpost_materials.py
python3 tools/export_evidence_index.py
python3 tools/video_rehearsal_gate.py
python3 tools/final_submission_gate.py
python3 tools/public_repo_preflight.py
python3 tools/submission_readiness_loop.py --full
python3 -m py_compile tests/test_observe_idempotency.py tests/test_budget.py tests/test_write_candidates.py tests/test_sqlite_event_store.py tests/test_observe_lifecycle.py tests/test_compile.py tests/test_providers.py tests/test_qwen_live_contract.py tests/test_qwen_live_e2e.py tests/test_qwen_live_embedding_baseline.py tests/test_hero_evaluation.py tests/test_micro_suite.py tests/test_demo.py tests/test_demo_server.py tests/test_judge_smoke.py tests/test_submission_packet.py tests/test_submission_docs.py tests/test_submission_bundle.py tools/build_demo_data.py tools/build_review_packet.py tools/build_submission_bundle.py tools/build_external_review_zip.py tools/fresh_clone_smoke.py tools/judge_smoke.py tools/run_live_qwen_contract.py tools/run_live_qwen_e2e.py tools/build_live_qwen_e2e_preflight.py tools/run_live_qwen_embedding_baseline.py tools/build_live_qwen_embedding_baseline_preflight.py tools/capture_demo_screenshots.py tools/devpost_preflight.py tools/export_devpost_materials.py tools/export_evidence_index.py tools/final_submission_gate.py tools/public_repo_preflight.py tools/submission_readiness_loop.py tools/video_rehearsal_gate.py src/recallpack/*.py
PYTHONPATH=src python3 -m unittest discover -s tests -v
node --check web/app.js
```

`python3 tools/devpost_preflight.py` is a local-only final check. It reports
`blocked_gated_actions` when local materials are ready but public repo URL,
presentation PPT upload/link, video URL/upload, final media order confirmation, or final Devpost approval
still require manual action.

`python3 tools/export_devpost_materials.py` is also local-only. It turns the
checked-in Devpost copy, media assets, verification evidence, and remaining
manual blockers into JSON/Markdown for manual copy/paste.

`python3 tools/export_evidence_index.py` is local-only. It maps core
judge-facing claims to evidence files, verification commands, risk levels, and
gated boundaries.

`python3 tools/video_rehearsal_gate.py` is local-only. It checks the recording
packet, screenshot assets, manual upload gates, public ECS wording, and
submission copy consistency before any video upload.

`python3 tools/final_submission_gate.py` is local-only. It aggregates Devpost
preflight, evidence index, public bundle scan, and full fresh-clone rehearsal
into one JSON report before media upload or final submission.

`python3 tools/public_repo_preflight.py` is local-only. It checks the sanitized
publish surface, MIT license, README, submission manifest, forbidden paths,
bundle scan, and judge commands before or after public GitHub repository
creation.

`python3 tools/submission_readiness_loop.py --full` is local-only. It aggregates
Devpost preflight, video rehearsal, public repo preflight, and the final
submission gate into one repeatable status report while keeping upload,
deployment, credential, and Devpost submit actions gated.

For the running backend:

```bash
PYTHONPATH=src python3 -m recallpack.demo_server --host 127.0.0.1 --port 8789
python3 tools/judge_smoke.py --url http://127.0.0.1:8789
```

## Approval-Only Actions

These remain blocked until the user explicitly approves them in the current
task:

- push further public repository changes;
- change repository visibility;
- push Docker images;
- run live Qwen again or read credentials;
- upload video or screenshots to Devpost;
- complete Devpost submission.

## Devpost Fields Still Needed

Before final submission, the user must provide or approve:

- public GitHub repository URL: https://github.com/cyq1017/recallpack;
- final video URL;
- final presentation PPT upload or link;
- final image gallery screenshots from `docs/submission/media/m71-replay/`;
- final project media order;
- confirmation that the project story still distinguishes credential-free local
  fake-provider runtime from the stored passing live Qwen E2E trace.

## No-Go Conditions

Do not submit if any of these are true:

- the public repo was created from the raw workspace instead of the sanitized
  bundle;
- `docs/execution/`, `AGENTS.md`, `dist/`, credentials, local SQLite state, or
  private paths are present in the public repository;
- `tools/fresh_clone_smoke.py --source . --full` fails in the public repo;
- `python3 tools/judge_smoke.py --url <public-or-local-url>` fails;
- README, review packet, or Devpost copy claims live Qwen E2E passed when the
  stored live observe/compile trace is not `live_e2e_passed`;
- project media implies a final video exists before upload;
- the public ECS endpoint is unreachable and no replacement deployment has
  been explicitly approved.

## Release Rule

Publish the sanitized bundle, not the raw workspace.

If the public repo is created manually, copy from the latest sanitized bundle
and then run the final judge commands above before adding the repo URL to
Devpost.
