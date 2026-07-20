# RecallPack

RecallPack is a MemoryAgent runtime for coding-agent handoffs. It prevents a
fresh coding agent from acting on project memory that a later session already
superseded.

Ordinary retrieval ranks similar history; it does not know which project
decision is still active. A coding agent can reason over stale context only if
the reversing decision also survives selection. Under a handoff budget,
selection happens before the agent reasons. RecallPack moves the decision
earlier: `/observe` records memory lifecycle state when old and new decisions
are visible together, and `/compile` later packs only active task-relevant
memory for the next agent.

The local demo shows the failure mode directly. In the source-backed
ProjectOdyssey JIT fixture, stale raw-history context keeps the old workaround,
applies the wrong patch, and passes only 1/3 fixture tests. RecallPack filters
the superseded memory, keeps the active fix-forward policy and project
preference, and the same temp-repo tests pass 3/3.

Run the judge smoke after creating the locked local environment:

```bash
python3 -m venv .venv
. .venv/bin/activate
python3 -m pip install -r requirements-v4.txt
```

```bash
PYTHONPATH=src python3 tools/fresh_clone_smoke.py --source .
```

The project also includes Qwen Cloud adapters, sanitized provider traces, eight
curated lifecycle fixtures, and a consent-first real-trace intake kit for
future evaluation hardening. Local demo and test paths are credential-free and
use deterministic provider-compatible fakes unless a live Qwen run is
explicitly approved.

For raw local trace candidates, first write a sanitized copy:

```bash
PYTHONPATH=src python3 tools/validate_real_trace_intake.py \
  --trace path/to/raw-trace.json \
  --sanitize \
  --sanitized-out path/to/sanitized-trace.json
```

## Evidence At A Glance

| Evidence | Status | What to trust |
| --- | --- | --- |
| Structural lifecycle claim | held in stored live runs | Superseded retry memory was excluded and active retry memory selected in stored live RecallPack runs. |
| Live raw-history embedding+rerank baseline | active selected in 2 stored runs | On this fixture, plain live retrieval also selected `session-a:turn-005`; the local replay is a failure-class illustration, not live frequency evidence. |
| Local scripted replay | baseline 1/3, RecallPack 3/3 | Authored deterministic demonstration of downstream risk when stale memory enters a budgeted handoff. |
| Eight curated lifecycle regression fixtures | local behavior contracts | Mechanism demonstration across retry, config, cache, serializer, pagination, API-client auth, source-backed provider-auth, and source-backed ProjectOdyssey JIT policy cases; not a broad benchmark. |
| Stored live Qwen provider-path traces | historical pass, M98 failed rerun, ProjectOdyssey passed | Integration evidence for the intended provider path. The latest ProjectOdyssey live run selected required active sources, excluded stale policy, and RecallPack live patch generation passed 3/3 fixture tests. The separate M98 retry-policy rerun remains failed evidence, so do not treat this as a broad live benchmark. |
| Public demo | credential-free deterministic replay | No live Qwen calls; uses sanitized trace evidence and fake providers for replay. |

## Limits

- Broad coding benchmark improvement.
- Universal retrieval superiority.
- Guaranteed live Qwen downstream success.
- Replacement for coding-agent reasoning.
- ProjectOdyssey production trace evidence; the ProjectOdyssey fixture is a
  source-backed synthetic scenario.

## Start Here For Judges

Run this first from the repository root if this is the published sanitized
repository:

```bash
python3 -m venv .venv
. .venv/bin/activate
python3 -m pip install -r requirements-v4.txt
```

```bash
PYTHONPATH=src python3 tools/fresh_clone_smoke.py --source .
```

That copies the public repo surface to a temp directory, rejects private or
generated paths, runs compile/unit/JS checks, starts the local server, and runs
the judge smoke. If you are inside the private working directory instead, use
the timestamped bundle flow in `Fresh Clone Quickstart`.

For a slower full-package rehearsal, run:

```bash
PYTHONPATH=src python3 tools/fresh_clone_smoke.py --source . --full
```

`--full` runs full public-test discovery inside the temp copy. Recursive
fresh-clone smoke tests and the custody-bound frozen-executor suite skip with
explicit reasons when its private frozen execution manifest is intentionally
absent from the public bundle; the private workspace runs that custody suite.

The fastest manual check is:

```bash
PYTHONPATH=src python3 -m unittest discover -s tests -v
```

Then start the demo server:

```bash
PYTHONPATH=src python3 -m recallpack.demo_server --host 127.0.0.1 --port 8789
```

In a second terminal, run the smoke check:

```bash
python3 tools/judge_smoke.py --url http://127.0.0.1:8789
```

Then open `http://127.0.0.1:8789/`. The first screen is a deterministic, fixture-backed demonstration of the MemoryAgent design: raw full-history
reference, keyword-scored fake-embedding + rerank raw-history baseline,
RecallPack stale-aware memory lifecycle, a one-click stale-memory failure
replay, and a first-run handoff simulator. Treat the replay as a scripted local
proof of downstream risk, not as a claim that live retrieval always selects the
stale item. The live evidence to trust for the structural claim is that
RecallPack excludes superseded memory before rerank and budget selection.

The repository includes Qwen Cloud adapters for memory decisions, embeddings,
and reranking, plus a sanitized standalone live API contract trace. The current
memory-decision adapter sends an OpenAI-compatible tool-calling request with
`tools`/`tool_choice` and defaults to `qwen3.7-plus-2026-05-26`. The checked-in
local demonstration uses deterministic providers and does not constitute an
end-to-end live-Qwen evaluation. The checked-in demo does not require Qwen credentials.
The current-model evidence is `docs/submission/live-qwen-e2e-trace.json`, not
the older standalone smoke trace. The standalone `live-qwen-trace.json` is kept
as a historical sanitized API contract smoke and may show an older text model.
For the local HTTP backend, `POST /compile` uses deterministic keyword fake
embedding/rerank providers through the same provider contract, so the public
smoke path is not zero-vector or identity-rerank smoke.
M43 adds a gated live Qwen E2E runner for the hero observe/compile lifecycle;
it is not run by local tests and requires `RECALLPACK_LIVE_QWEN_E2E_APPROVED=1`.
The stored live provider-path trace at
`docs/submission/live-qwen-e2e-trace.json` has `live_e2e_passed`: it records
one successful intended-provider-path run through live Qwen memory decisions,
`text-embedding-v4`, `qwen3-rerank`, and downstream patch generation. Treat it
as integration evidence, not statistical validation of live downstream
performance. No credentials are recorded in the trace.
The fresh M98 rerun is stored separately as
`docs/submission/live-qwen-m98-rerun-trace.json` with `live_e2e_failed`:
RecallPack still excluded stale memory and selected active retry memory, but
the downstream patch-generation delta did not reproduce 3/3. Treat the live
rerun as support for lifecycle filtering, not as a passing downstream headline.
The latest ProjectOdyssey live run is stored separately as
`docs/submission/projectodyssey-live-qwen-e2e-trace.json` with
`live_e2e_passed`: Qwen observed the source-backed scenario, selected
`session-h-current:turn-006` and `session-h-history:turn-004`, excluded the
stale `session-h-history:turn-002` policy, and recorded 32 sanitized provider
trace records. The live raw-history baseline passed 1/3 fixture tests while
RecallPack live-generated patch passed 3/3. Treat this as source-backed fixture
integration evidence, not as statistical validation of live downstream
performance.
M47 memory-decision contract hardening now sends structured event metadata,
explicit must-write/must-supersede policy, and a descriptive tool schema to the
Qwen text model. M64 extends the credential-free live E2E preflight so it
exercises observe, compile, and downstream patch-generation code paths with
fake HTTP responses. Run it before any approved live rerun:

```bash
PYTHONPATH=src python3 tools/build_live_qwen_e2e_preflight.py
```

This writes `docs/submission/live-qwen-e2e-preflight.json` with
`preflight_status=ready_for_live_e2e_rerun` and `network_calls_made=false`.
It does not require Qwen credentials, does not call Qwen, and should report
`request_role_counts=memory_decision=12 embedding=16 rerank=2 patch_generation=2`.

M76 adds a separate credential-free preflight for a real
`text-embedding-v4` raw-history baseline slice. It checks that the next
approved live baseline run will call the Qwen embedding endpoint for the goal
and all 12 raw session events, then pass embedding top-N into `qwen3-rerank`:

```bash
PYTHONPATH=src python3 tools/build_live_qwen_embedding_baseline_preflight.py
```

This writes `docs/submission/live-qwen-embedding-baseline-preflight.json` with
`preflight_status=ready_for_live_embedding_baseline_rerun`,
`request_role_counts=embedding=13 rerank=1`, and
`expected_selected_sources=session-a:turn-001,session-a:turn-003`. It is still
a no-network preflight; the actual live embedding baseline run remains gated.

Curated deterministic baseline comparison: raw full history is shown as a
reference and is not budget-comparable; the keyword-scored fake-embedding +
rerank raw-history baseline is selected from raw event text and reranked, not
source-picked from `gold.json` selected-source IDs. Its local scoring geometry
does use fixture-authored `baseline_embedding_terms` and
`baseline_downrank_phrases`, so treat the local numbers as a deterministic
demo replay. The live raw-history baseline path now has credential-free
preflight coverage and must be rerun with Qwen approval before being used as
the headline live baseline result.

Skeptical judge Q&A: `docs/submission/skeptical-judge-qa.md` maps each core
claim to code, tests, demo evidence, and stated limits.

Architecture Diagram: `docs/submission/architecture-diagram.md` shows the
judge-facing flow from Browser demo to Python demo backend, SQLite lifecycle
storage, Qwen text model, `text-embedding-v4`, `qwen3-rerank`, budget selector,
downstream evaluator, and Alibaba Cloud ECS runtime. It labels the local
credential-free proof path separately from the live-gated Qwen path.

Demo Video And Media Package: `docs/submission/demo-media-package.md` gives the
2:20-2:45 recording shot list, generated local Devpost screenshot candidates,
and acceptance checklist. Current screenshot PNGs are staged under
`docs/submission/media/m71-replay/`, and a local MP4 candidate is staged under
`docs/submission/media/video-candidate/`. No Devpost video URL or upload is
implied by the local package.

Blog Post Award Draft: `docs/submission/blog-post-draft.md` keeps the public
story focused on one claim: more context can make coding agents worse when old
decisions are stale.

Final Judge Rehearsal: `docs/submission/final-judge-rehearsal.md` tracks the
latest local package, the M98 evidence snapshot, the M104 public
ECS boundary, final judge commands, manual gates, and recording guardrails
before Devpost work.

Video Production Packet: `docs/submission/video-production-packet.md` is the
recording-day control packet: one-take run of show, retake triggers,
on-screen no-go list, upload package, and final self-check.

Recording Rehearsal Gate: `tools/video_rehearsal_gate.py` checks the recording
packet, screenshots, manual upload gates, public ECS wording, and local bundle
reference before recording. The latest local report is
`docs/submission/recording-rehearsal-report.md`. M104 keeps this packet honest
about the M98 evidence snapshot and the M104 public ECS boundary; do not treat
the latest local package as deployed without another redeploy and judge smoke
run.

Regenerate the local screenshot gallery while the demo server is running:

```bash
python3 tools/capture_demo_screenshots.py --url http://127.0.0.1:8789
```

Run the local Devpost preflight before manual submission:

```bash
python3 tools/devpost_preflight.py
python3 tools/export_devpost_materials.py
python3 tools/export_evidence_index.py
python3 tools/video_rehearsal_gate.py
python3 tools/final_submission_gate.py
python3 tools/public_repo_preflight.py
python3 tools/submission_readiness_loop.py --full
```

It does not read credentials, call Qwen, upload media, create a repository, or
submit Devpost. The preflight reports whether local materials are ready and
which manual gated actions still block submission. The materials export emits
JSON for structured review and Markdown for manual copy/paste into Devpost.
The evidence index maps judge-facing claims to evidence files and verification
commands for a final self-audit or external review.
The final submission gate aggregates preflight, evidence index, bundle scan,
and full fresh-clone rehearsal into one local JSON report before any manual
push, upload, or submission.
The submission readiness loop aggregates the local gates into one repeatable
status report and keeps manual actions separate from local readiness.
The public repo preflight checks the sanitized publish surface before manual
GitHub repository creation. It does not create a repository, push code, or
change visibility.

Public Release Gate: `docs/submission/public-release-gate.md` defines the final
approval-only gate for public repo creation and Devpost submission. It says to
publish the sanitized bundle, not the raw workspace, and lists the final judge
commands that must pass from the public repository root.

## Current Stage

This repository now has a local fixture-backed submission-ready package:

- ordered `/observe` runtime behavior and SQLite lifecycle storage;
- `/compile` read path with active-memory recall under an estimated 512-token
  serialized-memory budget, using deterministic keyword fake embedding/rerank
  providers for credential-free local HTTP smoke;
- Qwen provider contracts plus a sanitized live Qwen contract trace for
  memory decision, embedding, and rerank roles;
- memory-decision contract hardening for structured event metadata, explicit
  lifecycle policy, and descriptive tool schema fields;
- credential-free live E2E preflight for the hardened observe/compile path;
- gated live Qwen E2E runner for `ObserveRuntime` plus `/compile` provider
  execution; historical provider-path evidence includes one sanitized
  `live_e2e_passed` trace, a failed M98 retry-policy rerun, and a passing
  ProjectOdyssey live E2E trace;
- first-run handoff simulator showing a fresh coding agent receiving the retry
  task, stale raw-history baseline context, RecallPack active-memory context,
  and the downstream fixture-test result;
- eight downstream lifecycle fixtures: project-a retry helper, project-b config
  loader, project-c cache policy, project-d audit serializer, project-e
  pagination policy, project-f realistic API-client auth migration, and
  project-g source-backed provider auth-header mode, plus project-h
  source-backed ProjectOdyssey JIT policy;
- a consent-first real trace intake kit for future sanitized trace collection;
  it is not submission evidence until promoted;
- a 32-event behavior-contract fixture suite;
- curated deterministic baseline evidence with a raw full-history reference and
  keyword-scored fake-embedding + rerank raw-history baseline;
- local deterministic context-keyed patch-generation proof: baseline and
  RecallPack patches are generated from goal, selected context, and allowed edit
  paths without reading gold patch variants;
- a static Learn / Recall / Evaluate demo under `web/`;
- a stdlib demo backend target for `GET /api/demo`, `POST /observe`, and
  `POST /compile`.
- paste-ready review, skeptical judge Q&A, demo, submission, and gated-action
  approval docs under `docs/submission/`.
- a local-only Devpost preflight that checks prepared materials and reports
  manual gated actions without uploading or submitting anything.
- a local-only Devpost materials export that gathers copy-ready fields,
  screenshot assets, verification evidence, and remaining manual blockers.
- a local-only submission evidence index that maps core claims to source files,
  artifacts, commands, risk levels, and gated boundaries.
- a local-only final submission gate that aggregates preflight, evidence index,
  public bundle scan, and full fresh-clone rehearsal.
- a local-only public repo preflight that checks the sanitized publish surface,
  MIT license, README, manifest, forbidden paths, and judge commands before
  manual GitHub repository creation.
- a sanitized local submission bundle builder that excludes internal execution
  notes, generated caches, and machine-local paths.

V3.2.2 remains the implementation authority:

```bash
sed -n '1,260p' docs/plans/2026-06-24-recallpack-v3.2.2.md
```

## Local Demo

Regenerate static demo data:

```bash
PYTHONPATH=src python3 tools/build_demo_data.py
```

Open `web/index.html` directly, or run the local backend:

```bash
PYTHONPATH=src python3 -m recallpack.demo_server --host 127.0.0.1 --port 8789
```

Then open `http://127.0.0.1:8789/`.

## Fresh Clone Quickstart

RecallPack uses Python standard-library code for the local demo and tests. No
Qwen credentials are required for the local fake-provider test suite or for
viewing the checked-in demo payload.

From a fresh clone:

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
  tests/test_real_trace_intake.py \
  tools/build_demo_data.py tools/build_review_packet.py \
  tools/build_submission_bundle.py tools/build_external_review_zip.py \
  tools/fresh_clone_smoke.py \
  tools/judge_smoke.py tools/run_live_qwen_contract.py \
  tools/run_live_qwen_e2e.py tools/build_live_qwen_e2e_preflight.py \
  tools/run_live_qwen_embedding_baseline.py \
  tools/build_live_qwen_embedding_baseline_preflight.py \
  tools/capture_demo_screenshots.py tools/devpost_preflight.py \
  tools/export_devpost_materials.py tools/export_evidence_index.py \
  tools/final_submission_gate.py tools/public_repo_preflight.py \
  tools/submission_readiness_loop.py \
  tools/validate_real_trace_intake.py \
  tools/video_rehearsal_gate.py src/recallpack/*.py
PYTHONPATH=src python3 -m unittest discover -s tests -v
node --check web/app.js
```

To rehearse a published sanitized repository from its root:

```bash
PYTHONPATH=src python3 tools/fresh_clone_smoke.py --source .
PYTHONPATH=src python3 tools/fresh_clone_smoke.py --source . --full
```

To rehearse from this private working directory, build a sanitized bundle first:

```bash
bundle_target="dist/recallpack-submission-$(date +%Y%m%d-%H%M%S)"
PYTHONPATH=src python3 tools/build_submission_bundle.py --target "$bundle_target"
PYTHONPATH=src python3 tools/fresh_clone_smoke.py --source "$bundle_target"
PYTHONPATH=src python3 tools/fresh_clone_smoke.py --source "$bundle_target" --full
python3 tools/devpost_preflight.py
python3 tools/export_devpost_materials.py
python3 tools/export_evidence_index.py
python3 tools/video_rehearsal_gate.py
python3 tools/final_submission_gate.py
python3 tools/public_repo_preflight.py
python3 tools/submission_readiness_loop.py --full
```

Start the local server:

```bash
PYTHONPATH=src python3 -m recallpack.demo_server --host 127.0.0.1 --port 8789
```

In a second terminal:

```bash
python3 tools/judge_smoke.py --url http://127.0.0.1:8789
```

Then open `http://127.0.0.1:8789/`, or check the API directly:

```bash
curl http://127.0.0.1:8789/api/health
curl http://127.0.0.1:8789/api/demo
curl -X POST http://127.0.0.1:8789/observe \
  -H 'content-type: application/json' \
  -d '{"project_id":"project-a","session_id":"session-a","event_id":"turn-001","sequence_no":1,"actor":"user","kind":"message","observed_at":"2026-06-24T00:00:00Z","text":"Use three attempts with a fixed 100 ms delay in the retry helper."}'
curl -X POST http://127.0.0.1:8789/compile \
  -H 'content-type: application/json' \
  -d '{"project_id":"project-a","goal":"Update the retry helper to the current project policy.","component":"retry","budget_tokens":512}'
```

## Verification

```bash
PYTHONPATH=src python3 -m unittest discover -s tests -v
```

## Review Packet

Refresh the paste-ready review packet:

```bash
PYTHONPATH=src python3 tools/build_review_packet.py
```

Open:

```text
docs/submission/review-packet.md
docs/submission/skeptical-judge-qa.md
```

Build a local zip for GPT Pro, Claude, or another external reviewer from the
latest sanitized bundle:

```bash
python3 tools/build_external_review_zip.py \
  --source dist/recallpack-submission-YYYYMMDD-HHMMSS \
  --target dist/recallpack-external-review-$(date +%Y%m%d-%H%M%S).zip
```

The zip includes the sanitized bundle plus `EXTERNAL_REVIEW_PROMPT.md` and
`EXTERNAL_REVIEW_MANIFEST.json`. It refuses to package the raw workspace and
does not upload files, read credentials, or call Qwen.

## Live Qwen Contract

The local package can run a narrow Qwen Cloud contract proof when explicitly
approved:

```bash
read -s DASHSCOPE_API_KEY
export DASHSCOPE_API_KEY
export RECALLPACK_ENABLE_LIVE_QWEN=1
export RECALLPACK_LIVE_QWEN_APPROVED=1
export RECALLPACK_QWEN_BASE_URL="https://dashscope.aliyuncs.com/compatible-mode/v1"
export RECALLPACK_QWEN_RERANK_BASE_URL="https://dashscope.aliyuncs.com/compatible-api/v1"
PYTHONPATH=src python3 tools/run_live_qwen_contract.py
```

The generated `docs/submission/live-qwen-trace.json` stores only sanitized
provider roles, model names, request-id presence, and aggregate token usage. It
does not store credentials, raw prompts, raw memories, or tool arguments.

After separate approval, the gated live Qwen E2E runner exercises the hero
`ObserveRuntime` lifecycle and `/compile` path through Qwen providers. The
stored provider-path integration trace shows one successful intended live path;
it is not statistical validation of live downstream performance:

```bash
PYTHONPATH=src python3 tools/build_live_qwen_e2e_preflight.py
```

The preflight command above is credential-free. It records whether the hardened
request contract reaches memory_decision, embedding, and rerank in a no-network
fake-response run before any approved live rerun.

The real embedding baseline preflight is also credential-free:

```bash
PYTHONPATH=src python3 tools/build_live_qwen_embedding_baseline_preflight.py
```

After separate approval, the gated live embedding baseline runner can write
`docs/submission/live-qwen-embedding-baseline-trace.json`:

```bash
read -s DASHSCOPE_API_KEY
export DASHSCOPE_API_KEY
export RECALLPACK_ENABLE_LIVE_QWEN=1
export RECALLPACK_LIVE_QWEN_EMBEDDING_BASELINE_APPROVED=1
export RECALLPACK_QWEN_BASE_URL="https://dashscope.aliyuncs.com/compatible-mode/v1"
export RECALLPACK_QWEN_RERANK_BASE_URL="https://dashscope.aliyuncs.com/compatible-api/v1"
PYTHONPATH=src python3 tools/run_live_qwen_embedding_baseline.py
```

```bash
read -s DASHSCOPE_API_KEY
export DASHSCOPE_API_KEY
export RECALLPACK_ENABLE_LIVE_QWEN=1
export RECALLPACK_LIVE_QWEN_E2E_APPROVED=1
export RECALLPACK_LIVE_QWEN_E2E_TRACE_PATH="docs/submission/live-qwen-m98-rerun-trace.json"
export RECALLPACK_QWEN_BASE_URL="https://dashscope.aliyuncs.com/compatible-mode/v1"
export RECALLPACK_QWEN_RERANK_BASE_URL="https://dashscope.aliyuncs.com/compatible-api/v1"
PYTHONPATH=src python3 tools/run_live_qwen_e2e.py
```

The historical E2E report target is `docs/submission/live-qwen-e2e-trace.json`.
It is sanitized and should not contain credentials, raw prompts, raw memories,
or tool arguments. Historical stored provider-path integration status:
`live_e2e_passed`.

The fresh M98 rerun is stored separately at
`docs/submission/live-qwen-m98-rerun-trace.json` with `live_e2e_failed`:
observe/compile completed, but live patch generation did not pass 3/3 for
RecallPack. The stored `live_e2e_passed` trace demonstrates provider-path
integration; the M98 rerun demonstrates that downstream live reproducibility
remains an open empirical question. Do not claim the fresh M98 rerun passed
unless a later approved rerun writes a passing fresh trace.

The ProjectOdyssey live run is stored separately at
`docs/submission/projectodyssey-live-qwen-e2e-trace.json` with
`live_e2e_passed`. It ran against the China DashScope endpoints, selected both
required active sources, excluded the stale JIT policy, and recorded
memory=21722, embedding=727, rerank=474, and patch_generation=1963 token usage.
The live raw-history baseline passed 1/3 ProjectOdyssey fixture tests, while
RecallPack live-generated patch passed 3/3. The separate M98 retry-policy rerun
remains `live_e2e_failed`, so this should be presented as source-backed fixture
integration evidence rather than a broad live benchmark.

For gated actions that still require approval:

```text
docs/submission/gated-action-approval-matrix.md
docs/submission/gated-action-runbook.md
```

## Public Repository Boundary

Do not publish the raw workspace directly. Use the sanitized submission bundle
boundary documented in:

```text
docs/submission/public-repo-readiness-report.md
```

The public repository should exclude local execution notes, generated bundles,
cache files, local agent instructions, local environment files, and SQLite
state.

## Docker Quickstart

The Docker runtime can be built from the sanitized public bundle boundary and
run locally only on `127.0.0.1`:

```bash
bundle_target="dist/recallpack-submission-$(date +%Y%m%d-%H%M%S)"
PYTHONPATH=src python3 tools/build_submission_bundle.py --target "$bundle_target"
docker build -f "$bundle_target/deploy/alibaba-cloud/Dockerfile" \
  -t recallpack-demo:local "$bundle_target"
docker run --rm --name recallpack-local \
  -p 127.0.0.1:8789:8789 \
  -v recallpack-data:/data \
  recallpack-demo:local
```

Then check:

```bash
curl http://127.0.0.1:8789/
curl http://127.0.0.1:8789/api/health
curl http://127.0.0.1:8789/api/demo
curl -X POST http://127.0.0.1:8789/observe \
  -H 'content-type: application/json' \
  -d '{"project_id":"project-a","session_id":"session-a","event_id":"turn-001","sequence_no":1,"actor":"user","kind":"message","observed_at":"2026-06-24T00:00:00Z","text":"Use three attempts with a fixed 100 ms delay in the retry helper."}'
curl -X POST http://127.0.0.1:8789/compile \
  -H 'content-type: application/json' \
  -d '{"project_id":"project-a","goal":"Update the retry helper to the current project policy.","component":"retry","budget_tokens":512}'
```

## Submission Bundle

Build the local submission bundle from a clean target path:

```bash
bundle_target="dist/recallpack-submission-$(date +%Y%m%d-%H%M%S)"
PYTHONPATH=src python3 tools/build_submission_bundle.py --target "$bundle_target"
```

The builder refuses to overwrite an existing target. Use the generated
timestamped `dist/recallpack-submission-*` package for review/upload, not the
raw working directory.

## V3.2.2 Product Boundary

RecallPack manages advisory project memory only. It does not enforce policy,
approve actions, block tools, run Slack workflows, or share architecture with
TaskFence.

V3.2.2 keeps the MVP narrow:

- `POST /observe` for writing memories from raw session events.
- `POST /compile` for recalling active memories under an estimated fixed budget.
- SQLite for local persistent memory state.
- One 12-16 event hero coding fixture and a 32-event memory lifecycle
  micro-suite.
- Alibaba Cloud deployment proof after the local MVP is working.

## Non-Goals

- No Slack, GitHub, IDE, MCP, or general repo indexing.
- No vector database in the MVP.
- No context cache as a memory feature.
- No policy enforcement or approval workflow.
- No public submission, deployment, or publishing without explicit approval.
