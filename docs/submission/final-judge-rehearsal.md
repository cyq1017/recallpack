# RecallPack M67 Final Judge Rehearsal

Status: local-only submission surface freeze.

This document is the final local rehearsal map before video upload or Devpost
submission. It does not perform any public action.

## Submission Surface Freeze

No new product features should be added after this point unless they fix a
verified P0/P1 judge-facing blocker. M98 is the current local evidence
snapshot after adversarial review, and M99 keeps the current-package wording
aligned. M85 remains the internal deadline runway without adding new judge-facing product claims.

The frozen local evidence package is:

- latest local package and M98 evidence snapshot:
  `dist/recallpack-submission-20260720-231611/`.
- public GitHub repository:
  `https://github.com/cyq1017/recallpack`.
- M104 public ECS runtime from the prior verified deployment:
  `http://101.133.224.223/`.
- Stored live Qwen E2E trace:
  `docs/submission/live-qwen-e2e-trace.json` with `live_e2e_passed`.

The public repository URL is recorded, but this local rehearsal does not prove
the remote repository contains the latest sanitized bundle. For any future
update, publish the sanitized bundle, not the raw workspace. The raw workspace
contains execution notes, generated bundles, local agent rules, and local-only
context that should not be part of the judging repository.

## Final Judge Rehearsal Commands

Run these from the sanitized public repository root after it is created:

```bash
PYTHONPATH=src python3 tools/fresh_clone_smoke.py --source .
PYTHONPATH=src python3 tools/fresh_clone_smoke.py --source . --full
python3 tools/devpost_preflight.py
python3 tools/export_devpost_materials.py
python3 tools/export_evidence_index.py
python3 tools/final_submission_gate.py
python3 tools/public_repo_preflight.py
PYTHONPATH=src python3 -m unittest discover -s tests -v
node --check web/app.js
```

Run this against the existing approved public ECS endpoint as a liveness check:

```bash
PYTHONPATH=src python3 tools/judge_smoke.py --url http://101.133.224.223 --timeout 15
```

## Manual Gates

These remain manual and must not be treated as completed by local tests:

- final video URL or upload;
- final presentation PPT upload or link;
- final media order confirmation;
- final Devpost submit approval;
- any further ECS replacement or Docker image push.

## Claim Guardrails

- The latest local bundle is `dist/recallpack-submission-20260720-231611/`.
  The approved ECS endpoint still reflects the M104 credential-free runtime
  from `dist/recallpack-submission-20260704-123846/`; do not claim the 7/7
  bundle is deployed without another redeploy and judge smoke run.
- Fresh M98 live Qwen was rerun with approval and is stored as
  `docs/submission/live-qwen-m98-rerun-trace.json` with `live_e2e_failed`.
- Do not claim the fresh M98 live rerun passed; it completed observe/compile
  but live patch generation did not pass 3/3 for RecallPack.
- Do not rerun live Qwen without approval; it reads credentials and consumes
  quota.
- Do not claim eight fixtures are a broad benchmark.
- Do not claim the public demo endpoint performs live Qwen calls.
- Do not publish the raw workspace.

## Recording Priority

The final video should spend the first 90 seconds on the evidence boundary and
product proof:

- first 20 seconds: stale project memory is a handoff-selection problem, and
  RecallPack has a write-time information advantage because old and reversing
  decisions are visible together before budget selection;
- first 40 seconds: disclose that stored live RecallPack runs held lifecycle
  filtering, while stored live raw-history embedding+rerank baseline traces
  selected the active retry decision on this fixture;
- first 75 seconds: show the local deterministic replay as an authored
  failure-class illustration: baseline fixture tests are 1/3 and RecallPack
  fixture tests are 3/3.

After that, show active versus superseded memory, architecture, and the live
trace boundary. Keep the closing claim narrow: RecallPack is a MemoryAgent
lifecycle layer for coding-agent handoffs, not a generic agent platform.
