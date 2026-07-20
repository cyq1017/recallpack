# RecallPack Public Repository Readiness Report

Public repo readiness status: latest sanitized bundle is ready for public repo sync; remote freshness is not verified after M121.

Date: 2026-07-09

Public repository URL: https://github.com/cyq1017/recallpack

Latest local sanitized bundle: `dist/recallpack-submission-20260720-231611/`.
It includes M54 public release gate, M53 demo media package, M51 architecture
diagram, M50 external benchmark and winner polish, the 3-minute demo video
script, M55 Devpost screenshot gallery assets, the M56 reproducible capture
tool, the M57 Devpost preflight, the M58 Devpost materials export, the M59
submission evidence index, the M60 final submission gate, and the M61 public
repo preflight. M67 adds the final judge rehearsal and submission surface
freeze; M71 refreshes the first screen with a one-click stale-memory failure
replay; M85 adds internal deadline runway control without adding new
judge-facing product claims; M104 keeps recording and public materials honest
about the M104 prior verified ECS deployment.

M98 is the current evidence snapshot after adversarial review, M99 keeps the current-package wording aligned, M106 refreshes the local deadline/runway and remote-sync boundary, M120 ran ProjectOdyssey live Qwen E2E, and M121 hardens patch-generation path handling. The latest M121 bundle has not been pushed to the public repository in this local-only check.

Current public ECS deployment: M104 credential-free runtime built from the
prior verified bundle
`dist/recallpack-submission-20260704-123846/`. It runs
`recallpack-demo:m104-20260704-123846` tagged as `recallpack-demo:cloud`, with
`ThreadingHTTPServer` and judge smoke passing against the public URL.
Public ECS judge smoke passed after the M104 redeploy. Do not claim the latest
7/7 local bundle is deployed to ECS unless another redeploy and judge smoke run
is completed.

## Decision

Do not push the raw workspace as the judging repository.

The public repository URL is recorded, but this local report does not prove the
remote repository contains the latest sanitized submission bundle. Publish only
the bundle contents, or an equivalent whitelist matching
`tools/build_submission_bundle.py`. The raw workspace intentionally contains
local execution notes, generated bundles, local agent instructions, and cache
files that are not part of the public project surface.

## License Status

License status: MIT License present.

Root file:

```text
LICENSE
```

## Safe To Publish

Safe to publish:

- `LICENSE`
- `.gitignore`
- `README.md`
- `src/recallpack/`
- `tests/`
- `fixtures/`
- `web/`
- `tools/`
- `docs/submission/`
- `docs/submission/media/m71-replay/*.png`
- `docs/submission/public-release-gate.md`
- `docs/plans/2026-06-24-recallpack-v3.2.2.md`
- `docs/deployment/alibaba-cloud-proof.md`
- `deploy/alibaba-cloud/Dockerfile`

## Files To Exclude

Files to exclude:

- `AGENTS.md`
- `docs/execution/`
- `dist/`
- `__pycache__/`
- `.DS_Store`
- `.env`
- `.env.*`
- `*.pyc`
- `*.sqlite`
- `*.sqlite3`
- `*.db`

Rationale:

- `docs/execution/` is local collaboration and handoff history, not product
  documentation.
- `AGENTS.md` is local agent operating policy, not judge-facing project docs.
- `dist/` contains generated package copies and should be rebuilt from source.
- Environment and SQLite files can contain local machine state or credentials.

## Secret And Privacy Scan

Devpost screenshot gallery:

- `docs/submission/media/m71-replay/01-one-click-stale-memory-replay.png`
- `docs/submission/media/m71-replay/02-recallpack-active-memory-pack.png`
- `docs/submission/media/m71-replay/03-qwen-provider-evidence.png`
- regenerate locally with `python3 tools/capture_demo_screenshots.py --url http://127.0.0.1:8789`;
- `tools/capture_demo_screenshots.py --list` requires no Chrome, no server,
  no credentials, and no live Qwen call.
- capture mode accepts only local demo hosts and does not upload media.

Devpost preflight:

- `python3 tools/devpost_preflight.py` checks local submission materials,
  screenshot PNG dimensions, release-gate bundle evidence, and stored live
  Qwen E2E status.
- The expected pre-submission status is `blocked_gated_actions`, meaning local
  materials, public repo URL, and the required Devpost architecture/Alibaba
  Cloud proof image uploads are recorded ready with privacy checks, while final
  presentation PPT upload/link, video URL/upload, final media order confirmation, and final Devpost approval
  are still manual actions.
- It performs no network calls, reads no credentials, uploads no media, creates
  no public repository, and submits nothing.

Devpost materials export:

- `python3 tools/export_devpost_materials.py` emits copy-ready JSON to stdout
  and can write JSON/Markdown files for manual Devpost filling.
- The export combines `devpost-final-copy.md`, `hackathon-fields.md`, M57
  preflight evidence, screenshot assets, latest bundle evidence, and remaining
  manual blockers.
- It performs no network calls, reads no credentials, uploads no media, creates
  no public repository, and submits nothing.

Submission evidence index:

- `python3 tools/export_evidence_index.py` emits a local claim-to-evidence
  index for final self-audit and external review.
- The index maps MemoryAgent positioning, downstream stale handoff proof, Qwen
  provider integration, live Qwen E2E boundary, public repo boundary, and
  Devpost media readiness to evidence files, commands, risk levels, and gated
  boundaries.
- It performs no network calls, reads no credentials, uploads no media, creates
  no public repository, and submits nothing.

Final submission gate:

- `python3 tools/final_submission_gate.py` emits one local JSON gate report for
  pre-submission review.
- It aggregates Devpost preflight, submission evidence index, public bundle
  scan, and full fresh-clone rehearsal.
- It performs no credential reads, live Qwen calls, media upload, public repo
  creation, image push, or Devpost submission. Its fresh-clone rehearsal starts
  only a temporary local server for 127.0.0.1 smoke checks.

Public repo preflight:

- `python3 tools/public_repo_preflight.py` emits one local JSON report before
  or after public GitHub repository sync.
- It checks the sanitized publish surface, MIT license, README judge entry,
  submission manifest, forbidden paths, bundle scan, and judge commands.
- It performs no credential reads, live Qwen calls, repository creation, push,
  visibility change, media upload, or Devpost submission.

The submission bundle scan checks for:

- local machine path markers;
- high-confidence API token patterns;
- generated artifacts;
- internal execution files.

Current result:

```text
local_path_hits: 0
secret_hits: 0
generated_artifact_hits: 0
internal_path_hits: 0
```

No Qwen credentials are required for local tests. The checked-in live Qwen
trace is sanitized and records only provider roles, model names, request-id
presence, live flags, and aggregate token usage.

Local HTTP `/compile` uses deterministic keyword fake embedding/rerank
providers through the same provider interfaces as the Qwen adapters. This keeps
the public smoke path credential-free without reducing it to zero-vector or
identity-rerank behavior.

M43 adds `tools/run_live_qwen_e2e.py` for a separately approved live Qwen
observe/compile proof over the hero fixture. It is gated by
`RECALLPACK_ENABLE_LIVE_QWEN=1` and `RECALLPACK_LIVE_QWEN_E2E_APPROVED=1` and
is not run by local tests. The latest approved run wrote
`docs/submission/live-qwen-e2e-trace.json` with `live_e2e_passed`; it is
sanitized evidence of the live observe/compile/patch-generation path.
M48 adds `tools/build_live_qwen_e2e_preflight.py`, a credential-free no-network
preflight for the hardened observe/compile contract. M64 extends that preflight
through downstream patch generation using the same provider contract. It writes
`docs/submission/live-qwen-e2e-preflight.json` with
`preflight_status=ready_for_live_e2e_rerun`, `network_calls_made=false`, and
`request_role_counts=memory_decision=12 embedding=16 rerank=2 patch_generation=2`.
Future live Qwen E2E reruns remain gated because they read credentials and
consume API quota.

## Repo And Bundle Alignment

The public repository should match the same file boundary as the generated
bundle. Build it with:

```bash
bundle_target="dist/recallpack-submission-$(date +%Y%m%d-%H%M%S)"
PYTHONPATH=src python3 tools/build_submission_bundle.py --target "$bundle_target"
```

Then inspect `SUBMISSION_MANIFEST.md` inside the generated bundle before using
it as the public repository source.

M34 judge quick check manifest: passed.

`SUBMISSION_MANIFEST.md` now includes:

- MemoryAgent positioning;
- credential-free live E2E preflight command;
- credential-free fresh-clone smoke commands;
- local-only Devpost preflight command;
- local-only Devpost materials export command;
- local-only submission evidence index command;
- local-only final submission gate command;
- local-only public repo preflight command;
- `curl http://127.0.0.1:8789/api/health`;
- `tools/judge_smoke.py`;
- `GET /api/demo`, `POST /observe`, and `POST /compile` API surface notes.

M35 public surface completeness gate: passed.

`tools/fresh_clone_smoke.py` now rejects a public surface before server smoke if
required judge-facing files are missing or if `SUBMISSION_MANIFEST.md` does not
include the judge quick checks.

M36 static demo parity gate: passed.

`tools/fresh_clone_smoke.py` also rejects stale `web/demo-data.js` by comparing
the static demo payload with the current fixture-backed Python demo payload,
normalizing only dynamic memory IDs.

M29 fresh-clone rehearsal: passed.

M30 public repo root self-smoke: passed.

From a published sanitized repository clone, judges can run:

```bash
PYTHONPATH=src python3 tools/fresh_clone_smoke.py --source .
PYTHONPATH=src python3 tools/fresh_clone_smoke.py --source . --full
python3 tools/final_submission_gate.py
python3 tools/public_repo_preflight.py
```

Latest M121 final submission gate: passed against
`dist/recallpack-submission-20260720-231611/` with Devpost preflight, evidence
index, public bundle scan, and full fresh-clone rehearsal all passed.

Latest M121 public repo preflight: passed for the current sanitized bundle with
MIT license, README judge entry, submission manifest, forbidden paths, bundle
scan, and judge commands all passed. It records the public repo URL but does
not prove the latest M121 bundle has been pushed to GitHub.

M93 judge first-run command contract: `SUBMISSION_MANIFEST.md`,
`tools/public_repo_preflight.py`, README, and review packet copy-ready commands
share `JUDGE_FIRST_RUN_COMMANDS`, preventing judge setup instructions from
drifting across public surfaces.

M94 public release gate command contract: `docs/submission/public-release-gate.md`
now includes every command from `JUDGE_FIRST_RUN_COMMANDS`, including the video
rehearsal gate, so the manual pre-publication checklist matches the judge
quickstart.

M106 current-day release readiness refresh: this report and local readiness now
use `Date: 2026-07-07`; the internal deadline runway reference is
`2026-07-07 10:43 CST` with about 2 days 18 hours 17 minutes remaining. This is
date/readiness maintenance only, not a new product claim.

M96 current-package wording guardrail: judge-facing recording, review,
public-repo, and generated packet surfaces now use version-neutral latest local
package wording instead of calling M90 the current package. This is claim
consistency maintenance, not a new product feature.

M97 source-to-bundle parity preflight: when run from the raw workspace,
`tools/public_repo_preflight.py` now compares all public-bundle source files
against the latest sanitized bundle and fails if docs or code changed after the
bundle was built. When run from a sanitized bundle root, the check is marked
passed/skipped because the bundle is already the publish surface.

From the private working directory, rehearse that public surface from a
temporary copy with:

```bash
PYTHONPATH=src python3 tools/fresh_clone_smoke.py --source "$bundle_target"
PYTHONPATH=src python3 tools/fresh_clone_smoke.py --source "$bundle_target" --full
```

The rehearsal copies the bundle to a temp directory, rejects internal/private
paths, runs py_compile, a focused unittest subset, `node --check web/app.js`,
and the local demo `tools/judge_smoke.py`.

Full fresh-clone rehearsal command: add `--full` to run full public-test
discovery in the temp copy. The child run skips recursive fresh-clone smoke
tests and the custody-bound frozen-executor suite when its private frozen
execution manifest is intentionally absent from the public bundle; those
private custody tests still run in the private workspace before release.

Judge-facing review docs include `docs/submission/review-packet.md` and
`docs/submission/skeptical-judge-qa.md`.

## Docker Runtime Proof

Docker proof: local 127.0.0.1 runtime passed.

M104 Docker proof: passed from the prior verified public ECS bundle.

The latest completed local Docker proof ran
`recallpack-demo:m104-20260704-123846` from the checked-in Dockerfile with:

```bash
docker buildx build --platform linux/amd64 --load \
  -f deploy/alibaba-cloud/Dockerfile \
  -t recallpack-demo:m104-20260704-123846 \
  .
docker run --rm --name recallpack-m102-local \
  -p 127.0.0.1:8817:8789 \
  recallpack-demo:m104-20260704-123846
```

Smoke results:

- `GET /` returned HTTP 200.
- `GET /api/health exposes compact readiness` with MemoryAgent track,
  `live_contract_passed`, Qwen provider roles, fixture count, and baseline
  1/3 versus RecallPack 3/3.
- `GET /api/demo` returned `live_contract_passed`.
- `GET /api/demo` showed baseline 1/3 and RecallPack 3/3.
- `GET /api/demo` smoke now hard-gates `live_contract_passed`, first-screen
  downstream test ratios, retrieval path, and Qwen provider roles.
- `GET /api/demo` exposes a raw full-history reference plus computed
  embedding top-N + rerank RAG baseline; the stale baseline is not fixture-selected from
  `gold.json`.
- `GET /api/demo` exposes `judge_first_screen` with Qwen model work versus
  deterministic runtime work.
- `GET /api/demo` exposes the M45 first-run handoff simulator with baseline
  1/3 and RecallPack 3/3.
- `GET /api/demo` exposes the M23/M77/M110/M113/M117 eight curated lifecycle
  fixtures for project-a retry, project-b config loader, project-c cache
  policy, project-d audit serializer, project-e pagination, project-f
  API-client auth, project-g provider-auth mode, and project-h ProjectOdyssey
  JIT policy.
- POST /observe writes an auth decision memory in judge smoke, while retry
  compile proof is seeded through HTTP observe events.
- `POST /compile` included `session-a:turn-005`.
- `POST /compile` included `session-a:turn-003`.
- `POST /compile` excluded stale `session-a:turn-001`.

No image was pushed to a registry and no hackathon submission was performed.
After explicit user approval, the Alibaba Cloud ECS public demo endpoint at
`http://101.133.224.223/` was redeployed from the M104 sanitized bundle and
passed judge smoke. The latest 7/7 local bundle has not been claimed as
redeployed to ECS.

## Judge Smoke Commands

Judge smoke commands:

```bash
python3 -m py_compile tests/test_observe_idempotency.py tests/test_budget.py tests/test_write_candidates.py tests/test_sqlite_event_store.py tests/test_observe_lifecycle.py tests/test_compile.py tests/test_providers.py tests/test_qwen_live_contract.py tests/test_qwen_live_e2e.py tests/test_qwen_live_embedding_baseline.py tests/test_hero_evaluation.py tests/test_micro_suite.py tests/test_demo.py tests/test_demo_server.py tests/test_judge_smoke.py tests/test_submission_packet.py tests/test_submission_docs.py tests/test_submission_bundle.py tools/build_demo_data.py tools/build_review_packet.py tools/build_submission_bundle.py tools/fresh_clone_smoke.py tools/judge_smoke.py tools/run_live_qwen_contract.py tools/run_live_qwen_e2e.py tools/build_live_qwen_e2e_preflight.py tools/run_live_qwen_embedding_baseline.py tools/build_live_qwen_embedding_baseline_preflight.py tools/capture_demo_screenshots.py tools/devpost_preflight.py tools/export_devpost_materials.py tools/export_evidence_index.py tools/final_submission_gate.py tools/public_repo_preflight.py tools/video_rehearsal_gate.py src/recallpack/*.py
PYTHONPATH=src python3 -m unittest discover -s tests -v
node --check web/app.js
```

Start the local server:

```bash
PYTHONPATH=src python3 -m recallpack.demo_server --host 127.0.0.1 --port 8789
```

In a second terminal, run:

```bash
python3 tools/judge_smoke.py --url http://127.0.0.1:8789
curl http://127.0.0.1:8789/api/health
curl http://127.0.0.1:8789/api/demo
curl -X POST http://127.0.0.1:8789/observe \
  -H 'content-type: application/json' \
  -d '{"project_id":"project-a","session_id":"session-a","event_id":"turn-001","sequence_no":1,"actor":"user","kind":"message","observed_at":"2026-06-24T00:00:00Z","text":"Use three attempts with a fixed 100 ms delay in the retry helper."}'
curl -X POST http://127.0.0.1:8789/compile \
  -H 'content-type: application/json' \
  -d '{"project_id":"project-a","goal":"Update the retry helper to the current project policy.","component":"retry","budget_tokens":512}'
```

Expected `/compile` behavior:

- includes `session-a:turn-005`;
- includes `session-a:turn-003`;
- excludes stale `session-a:turn-001`.

## Future Public Repository Update Checklist

- Rotate any API key that was pasted into chat or other non-secret channels.
- Use the sanitized bundle boundary, not the raw workspace.
- Run the full verification commands after the final bundle is built.
- Inspect tracked filenames and changed content before any future push.
- Fresh-clone the public repository and rerun judge commands after any future
  sync.
- Confirm the repository remains public and the MIT license is detected by
  GitHub.

## Still Gated

- Any additional live Qwen credential access or contract rerun.
- Docker build/run if local container runtime is considered gated.
- Image push.
- Any further Alibaba Cloud ECS creation or replacement.
- Any further public endpoint exposure or replacement.
- Hackathon submission.
